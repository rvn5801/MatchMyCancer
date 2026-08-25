"""Tests for corpus ingestion and the corpus schema.

No network: project resolution is the only networked step and it is a separate
function, so tar parsing and storage are testable offline.
"""

import io
import tarfile

import pytest

from app.evaluation import corpus_db
from app.evaluation.build_corpus import CorpusError, ingest_tar, parse_member_name

UUID_A = "02968a64-a0b5-410e-b56d-f065c60e68fe"
UUID_B = "13a79b75-b1c6-521f-c67e-a176d71f79ff"


def _make_tar(path, members: dict[str, bytes]):
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


class TestParseMemberName:
    def test_real_gdc_layout(self):
        name = f"{UUID_A}/TCGA-B1-A656.F08B2D8F-D5D3-4DCC-9E7B-EE6D655712BD.PDF"
        assert parse_member_name(name) == {
            "file_id": UUID_A,
            "barcode": "TCGA-B1-A656",
            "filename": "TCGA-B1-A656.F08B2D8F-D5D3-4DCC-9E7B-EE6D655712BD.PDF",
        }

    def test_manifest_is_skipped(self):
        assert parse_member_name("MANIFEST.txt") is None

    def test_bad_barcode_raises(self):
        """A silent skip here would quietly shrink the corpus."""
        with pytest.raises(CorpusError, match="barcode"):
            parse_member_name(f"{UUID_A}/NOT-A-BARCODE.abc.PDF")

    def test_non_uuid_directory_raises(self):
        """file_id becomes a path component — it must not be trusted."""
        with pytest.raises(CorpusError, match="UUID"):
            parse_member_name("notauuid/TCGA-B1-A656.x.PDF")

    def test_unexpected_depth_raises(self):
        with pytest.raises(CorpusError, match="layout"):
            parse_member_name(f"extra/{UUID_A}/TCGA-B1-A656.x.PDF")

    @pytest.mark.parametrize(
        "name",
        [
            "../../etc/TCGA-B1-A656.x.PDF",
            "../TCGA-B1-A656.x.PDF",
            "/abs/TCGA-B1-A656.x.PDF",
        ],
    )
    def test_traversal_attempts_rejected(self, name):
        """Any name that could escape the output directory must not parse."""
        with pytest.raises(CorpusError):
            parse_member_name(name)


class TestIngestTar:
    def test_extracts_pdfs_and_skips_manifest(self, tmp_path):
        tar_path = tmp_path / "gdc.tar.gz"
        _make_tar(
            tar_path,
            {
                "MANIFEST.txt": b"id\tfilename\n",
                f"{UUID_A}/TCGA-B1-A656.aaa.PDF": b"%PDF-1.4 first",
                f"{UUID_B}/TCGA-05-4395.bbb.PDF": b"%PDF-1.4 second",
            },
        )

        pdf_dir = tmp_path / "pdf"
        records = ingest_tar(tar_path, pdf_dir)

        assert len(records) == 2
        assert {r["barcode"] for r in records} == {"TCGA-B1-A656", "TCGA-05-4395"}
        assert (pdf_dir / f"{UUID_A}.pdf").read_bytes() == b"%PDF-1.4 first"
        assert (pdf_dir / f"{UUID_B}.pdf").read_bytes() == b"%PDF-1.4 second"

    def test_pdfs_are_written_under_pdf_dir_only(self, tmp_path):
        """Member names must never escape the output directory."""
        tar_path = tmp_path / "evil.tar.gz"
        _make_tar(tar_path, {"../../escaped/TCGA-B1-A656.x.PDF": b"%PDF"})

        with pytest.raises(CorpusError):
            ingest_tar(tar_path, tmp_path / "pdf")
        assert not (tmp_path.parent / "escaped").exists()


class TestCorpusDb:
    def test_schema_round_trip(self, tmp_path):
        conn = corpus_db.connect(tmp_path / "corpus.db")
        conn.execute(
            "INSERT INTO report (file_id, barcode, project, filename) VALUES (?,?,?,?)",
            (UUID_A, "TCGA-B1-A656", "TCGA-KIRP", "TCGA-B1-A656.aaa.PDF"),
        )
        row = conn.execute("SELECT * FROM report").fetchone()
        assert row["barcode"] == "TCGA-B1-A656"
        assert row["page_count"] is None

    def test_connect_is_idempotent(self, tmp_path):
        """Re-opening an existing corpus must not wipe or error."""
        db = tmp_path / "corpus.db"
        conn = corpus_db.connect(db)
        conn.execute(
            "INSERT INTO report (file_id, barcode, project, filename) VALUES (?,?,?,?)",
            (UUID_A, "TCGA-B1-A656", "TCGA-KIRP", "a.PDF"),
        )
        conn.commit()
        conn.close()

        again = corpus_db.connect(db)
        assert again.execute("SELECT COUNT(*) AS n FROM report").fetchone()["n"] == 1

    def test_one_patient_can_have_several_reports(self, tmp_path):
        """11,324 files across 11,237 cases — keying on barcode would drop rows."""
        conn = corpus_db.connect(tmp_path / "corpus.db")
        for file_id in (UUID_A, UUID_B):
            conn.execute(
                "INSERT INTO report (file_id, barcode, project, filename) "
                "VALUES (?,?,?,?)",
                (file_id, "TCGA-B1-A656", "TCGA-KIRP", f"{file_id}.PDF"),
            )
        assert conn.execute("SELECT COUNT(*) AS n FROM report").fetchone()["n"] == 2

    def test_meta_helpers(self, tmp_path):
        conn = corpus_db.connect(tmp_path / "corpus.db")
        corpus_db.set_meta(conn, "corpus_report_count", 11324)
        assert corpus_db.get_meta(conn, "corpus_report_count") == "11324"
        assert corpus_db.get_meta(conn, "absent") is None
