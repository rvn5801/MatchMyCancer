"""Download TCGA pathology report PDFs directly from the GDC API.

Replaces the portal cart workflow: the filters live in code, every file
downloads individually (no 3 GB tarball to fail halfway), and the run is
resumable — kill it anytime and rerun; already-downloaded reports are skipped.

Usage:
  cd backend && source .venv/bin/activate

  # Pilot: two projects, capped
  python -m app.evaluation.fetch_pathology_reports --project TCGA-LUAD --project TCGA-SKCM --limit 200

  # Everything (~11,200 PDFs, ~3 GB)
  python -m app.evaluation.fetch_pathology_reports

Feeds the same corpus.db as build_corpus.py; extract_text.py runs next.
"""

import argparse
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx

from app.evaluation import corpus_db
from app.evaluation.build_corpus import BARCODE_RE

GDC_FILES_URL = "https://api.gdc.cancer.gov/files"
GDC_DATA_URL = "https://api.gdc.cancer.gov/data"

PAGE_SIZE = 500


def build_filters(projects: Optional[List[str]]) -> Dict[str, Any]:
    """The portal filter set, as code: open-access TCGA pathology report PDFs."""
    clauses = [
        {"op": "in", "content": {"field": "data_type", "value": ["Pathology Report"]}},
        {"op": "in", "content": {"field": "data_format", "value": ["PDF"]}},
        {"op": "in", "content": {"field": "access", "value": ["open"]}},
        {"op": "in", "content": {"field": "cases.project.program.name", "value": ["TCGA"]}},
    ]
    if projects:
        clauses.append(
            {"op": "in", "content": {"field": "cases.project.project_id", "value": projects}}
        )
    return {"op": "and", "content": clauses}


def iter_report_files(
    projects: Optional[List[str]] = None,
) -> Iterator[Dict[str, str]]:
    """Yield {file_id, file_name, barcode, project} for every matching report."""
    start = 0
    while True:
        resp = httpx.post(
            GDC_FILES_URL,
            json={
                "filters": build_filters(projects),
                "fields": "file_id,file_name,cases.submitter_id,cases.project.project_id",
                "from": start,
                "size": PAGE_SIZE,
                "format": "JSON",
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()["data"]

        for hit in data["hits"]:
            cases = hit.get("cases") or []
            if not cases:
                continue
            yield {
                "file_id": hit["file_id"],
                "file_name": hit.get("file_name", ""),
                "barcode": cases[0].get("submitter_id", ""),
                "project": (cases[0].get("project") or {}).get("project_id", ""),
            }

        pag = data["pagination"]
        start += PAGE_SIZE
        if start >= pag["total"]:
            return


def download_pdf(file_id: str, dest: Path, retries: int = 3) -> None:
    """Download one report. Writes atomically so a killed run leaves no
    half-files that a resume would mistake for complete."""
    tmp = dest.with_suffix(".part")
    for attempt in range(1, retries + 1):
        try:
            with httpx.stream("GET", f"{GDC_DATA_URL}/{file_id}", timeout=180) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(65536):
                        f.write(chunk)
            tmp.rename(dest)
            return
        except (httpx.HTTPError, OSError):
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download TCGA pathology report PDFs from the GDC API"
    )
    parser.add_argument(
        "--project", action="append", default=None,
        help="restrict to a project, e.g. --project TCGA-LUAD (repeatable)",
    )
    parser.add_argument("--limit", type=int, default=None, help="stop after N reports")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--pdf-dir", type=Path,
        default=Path(__file__).parent / "corpus" / "pdf",
    )
    args = parser.parse_args()

    args.pdf_dir.mkdir(parents=True, exist_ok=True)
    conn = corpus_db.connect(args.db)

    have = {
        r["file_id"]
        for r in conn.execute("SELECT file_id FROM report").fetchall()
        if (args.pdf_dir / f"{r['file_id']}.pdf").exists()
    }
    print(f"already in corpus: {len(have)}")

    stats = {"new": 0, "skipped": 0, "bad_barcode": 0, "failed": 0}
    seen = 0

    for rec in iter_report_files(args.project):
        if args.limit and stats["new"] + stats["skipped"] >= args.limit:
            break
        seen += 1

        if rec["file_id"] in have:
            stats["skipped"] += 1
            continue
        # A bad join key poisons every downstream label lookup — refuse it.
        if not BARCODE_RE.match(rec["barcode"]) or not rec["project"]:
            stats["bad_barcode"] += 1
            print(f"  SKIP bad metadata: {rec['file_id']} barcode={rec['barcode']!r}")
            continue

        dest = args.pdf_dir / f"{rec['file_id']}.pdf"
        try:
            download_pdf(rec["file_id"], dest)
        except Exception as e:  # noqa: BLE001 — counted and shown, run continues
            stats["failed"] += 1
            print(f"  FAILED {rec['file_id']}: {e}")
            continue

        conn.execute(
            "INSERT OR IGNORE INTO report (file_id, barcode, project, filename) "
            "VALUES (?, ?, ?, ?)",
            (rec["file_id"], rec["barcode"], rec["project"], rec["file_name"]),
        )
        stats["new"] += 1
        if stats["new"] % 25 == 0:
            conn.commit()
            print(f"  {stats['new']} downloaded ({seen} listed)...")

    corpus_db.set_meta(conn, "fetch_projects", ",".join(args.project or ["ALL-TCGA"]))
    conn.commit()

    total = conn.execute("SELECT COUNT(*) AS n FROM report").fetchone()["n"]
    print(
        f"\ndone: new={stats['new']} already-had={stats['skipped']} "
        f"bad-metadata={stats['bad_barcode']} failed={stats['failed']}"
    )
    print(f"corpus now holds {total} reports")
    if stats["failed"]:
        print("re-run to retry failures — completed files are skipped automatically")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
