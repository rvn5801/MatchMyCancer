"""Ingest GDC pathology report tarballs into the corpus database.

The GDC portal delivers a multi-file cart download as .tar.gz laid out as:

    MANIFEST.txt
    {file_id}/{barcode}.{uuid}.PDF

The patient barcode is in the filename, so the join key to cBioPortal costs
nothing — no per-file API call is needed to build the corpus.

Usage:
  cd backend && source .venv/bin/activate
  python -m app.evaluation.build_corpus ~/Downloads/gdc_download_*.tar.gz

Re-running the same tarball is a no-op; adding another is additive.
"""

import argparse
import re
import sys
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.evaluation import corpus_db

GDC_FILES_URL = "https://api.gdc.cancer.gov/files"

# GDC accepts large POST bodies, but chunking keeps one bad response from
# taking down an entire 11k-file resolution pass.
RESOLVE_CHUNK = 500

BARCODE_RE = re.compile(r"^TCGA-[0-9A-Z]{2}-[0-9A-Z]{4}$")

# file_id becomes a path component below, so it is validated as a UUID rather
# than trusted. Tar member names are attacker-controlled in the general case.
FILE_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class CorpusError(Exception):
    """A malformed tar member — never swallowed, always names the member."""


def parse_member_name(name: str) -> Optional[Dict[str, str]]:
    """Parse '{file_id}/{barcode}.{uuid}.PDF' into its parts.

    Returns None for members that are not report PDFs (MANIFEST.txt, directory
    entries). Raises CorpusError for a PDF whose name does not parse — a silent
    skip there would quietly shrink the corpus.
    """
    if not name.lower().endswith(".pdf"):
        return None

    parts = name.split("/")
    if len(parts) != 2:
        raise CorpusError(f"unexpected member layout: {name!r}")

    file_id, filename = parts
    if not FILE_ID_RE.match(file_id):
        raise CorpusError(f"member directory is not a UUID: {name!r}")

    barcode = filename.split(".")[0]
    if not BARCODE_RE.match(barcode):
        raise CorpusError(f"filename does not start with a TCGA barcode: {name!r}")

    return {"file_id": file_id, "barcode": barcode, "filename": filename}


def ingest_tar(tar_path: Path, pdf_dir: Path) -> List[Dict[str, str]]:
    """Extract report PDFs from one tarball and return their metadata.

    Members are read individually and written to a path built from the
    validated file_id. extractall() is deliberately not used — it honours
    paths inside the archive.
    """
    pdf_dir.mkdir(parents=True, exist_ok=True)
    records: List[Dict[str, str]] = []

    with tarfile.open(tar_path, "r:*") as tar:
        for member in tar:
            if not member.isfile():
                continue
            parsed = parse_member_name(member.name)
            if parsed is None:
                continue

            source = tar.extractfile(member)
            if source is None:
                raise CorpusError(f"could not read member: {member.name!r}")
            (pdf_dir / f"{parsed['file_id']}.pdf").write_bytes(source.read())
            records.append(parsed)

    return records


def resolve_projects(file_ids: List[str]) -> Dict[str, Dict[str, str]]:
    """Look up project and barcode for each file_id from the GDC API.

    The tar carries no project information. The API also returns the case
    submitter_id, which cross-checks the filename parse for free.
    """
    resolved: Dict[str, Dict[str, str]] = {}

    for start in range(0, len(file_ids), RESOLVE_CHUNK):
        chunk = file_ids[start : start + RESOLVE_CHUNK]
        resp = httpx.post(
            GDC_FILES_URL,
            json={
                "filters": {
                    "op": "in",
                    "content": {"field": "file_id", "value": chunk},
                },
                "fields": "file_id,cases.project.project_id,cases.submitter_id",
                "size": len(chunk),
                "format": "JSON",
            },
            timeout=120,
        )
        resp.raise_for_status()

        for hit in resp.json()["data"]["hits"]:
            cases = hit.get("cases") or []
            if not cases:
                continue
            project = (cases[0].get("project") or {}).get("project_id")
            if not project:
                continue
            resolved[hit["file_id"]] = {
                "project": project,
                "barcode": cases[0].get("submitter_id", ""),
            }

        print(f"  resolved {len(resolved)}/{len(file_ids)}")

    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest GDC pathology report tarballs into the corpus database"
    )
    parser.add_argument("tarballs", nargs="+", type=Path, help="GDC .tar.gz downloads")
    parser.add_argument("--db", type=Path, default=None, help="corpus database path")
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=Path(__file__).parent / "corpus" / "pdf",
        help="where extracted PDFs are written",
    )
    args = parser.parse_args()

    records: List[Dict[str, str]] = []
    for tar_path in args.tarballs:
        if not tar_path.exists():
            print(f"ERROR: no such file: {tar_path}", file=sys.stderr)
            return 1
        found = ingest_tar(tar_path, args.pdf_dir)
        print(f"{tar_path.name}: {len(found)} report PDFs")
        records.extend(found)

    if not records:
        print("ERROR: no report PDFs found in the given tarballs", file=sys.stderr)
        return 1

    # Duplicate file_ids across tarballs are expected if carts overlap.
    by_id = {r["file_id"]: r for r in records}
    print(f"\n{len(by_id)} unique reports; resolving projects from GDC...")
    resolved = resolve_projects(sorted(by_id))

    conn = corpus_db.connect(args.db)
    inserted = 0
    unresolved: List[str] = []
    mismatched: List[str] = []

    for file_id, rec in sorted(by_id.items()):
        info = resolved.get(file_id)
        if info is None:
            unresolved.append(file_id)
            continue
        # A filename barcode that disagrees with the API is a corrupt join key.
        # Every downstream label lookup depends on it, so this is fatal.
        if info["barcode"] and info["barcode"] != rec["barcode"]:
            mismatched.append(
                f"{file_id}: filename={rec['barcode']} api={info['barcode']}"
            )
            continue
        conn.execute(
            "INSERT OR IGNORE INTO report (file_id, barcode, project, filename) "
            "VALUES (?, ?, ?, ?)",
            (file_id, rec["barcode"], info["project"], rec["filename"]),
        )
        inserted += 1

    corpus_db.set_meta(conn, "corpus_tarballs", ", ".join(t.name for t in args.tarballs))
    corpus_db.set_meta(conn, "corpus_report_count", inserted)
    conn.commit()

    total = conn.execute("SELECT COUNT(*) AS n FROM report").fetchone()["n"]
    print(f"\ninserted/updated {inserted} reports; {total} in database")

    if mismatched:
        print(f"\nERROR: {len(mismatched)} barcode mismatches — these were NOT inserted:")
        for line in mismatched[:20]:
            print(f"  {line}")
        return 1
    if unresolved:
        print(
            f"\nWARNING: {len(unresolved)} file_ids had no GDC project and were "
            f"skipped (project is required for the cBioPortal join):"
        )
        for file_id in unresolved[:20]:
            print(f"  {file_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
