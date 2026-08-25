"""Extract text from corpus PDFs, one method per run.

Real TCGA pathology PDFs are mostly scans that already carry a text layer from
an older OCR pass, so several extraction methods produce genuinely different
text for the same document. Keeping them side by side is what lets the audit
separate "the value is not in the report" from "the value is there but the
transcription mangled it".

Methods:
  embedded         page.get_text()               — current production behaviour
  embedded_sorted  page.get_text(sort=True)      — reading order by position
  tesseract5       rasterise 200 DPI + Tesseract — ignores the embedded layer

The presence audit runs on embedded_sorted. Both embedded methods cover the
full corpus in minutes; tesseract5 costs ~1.4s per report and belongs to the
separate OCR comparison study, so it is not on this study's critical path.

Usage:
  cd backend && source .venv/bin/activate
  python -m app.evaluation.extract_text --method embedded_sorted
  python -m app.evaluation.extract_text --method tesseract5 --project TCGA-LUAD --limit 200

Re-running skips reports already done for that method unless --force.
"""

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import fitz

from app.evaluation import corpus_db
from app.services.ocr_engine import ocr_image

DEFAULT_PDF_DIR = Path(__file__).parent / "corpus" / "pdf"

OCR_DPI = 200

# Deliberately no page cap here, unlike the request-serving pipeline's
# MAX_OCR_PAGES. Truncating long reports would bias the presence audit toward
# findings that happen to sit on early pages.


def _embedded(doc: fitz.Document, sort: bool) -> str:
    return "\n\n".join(page.get_text("text", sort=sort) for page in doc)


def _tesseract(doc: fitz.Document) -> str:
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=OCR_DPI)
        pages.append(ocr_image(pix.tobytes("png"))["text"])
    return "\n\n".join(pages)


METHODS: dict[str, Callable[[fitz.Document], str]] = {
    "embedded": lambda doc: _embedded(doc, sort=False),
    "embedded_sorted": lambda doc: _embedded(doc, sort=True),
    "tesseract5": _tesseract,
}

# Methods that rasterise and re-OCR. ~1.4s per report against ~14ms for the
# embedded layer, so running one over the full corpus is a multi-hour job.
OCR_METHODS = {"tesseract5"}


def record_tool_versions(conn, method: str) -> None:
    """Store the exact tool versions a run used.

    A presence rate is not reproducible without them, and the Tesseract version
    matters most — a later release fixes different characters.
    """
    corpus_db.set_meta(conn, f"extract.{method}.pymupdf", fitz.__version__)
    corpus_db.set_meta(conn, f"extract.{method}.mupdf", fitz.version[1])
    corpus_db.set_meta(
        conn, f"extract.{method}.run_at", datetime.now(timezone.utc).isoformat()
    )
    if method in OCR_METHODS:
        import pytesseract

        corpus_db.set_meta(
            conn, f"extract.{method}.tesseract", str(pytesseract.get_tesseract_version())
        )
        corpus_db.set_meta(conn, f"extract.{method}.dpi", OCR_DPI)


def extract_one(pdf_path: Path, method: str) -> dict:
    """Run one extraction method over one PDF.

    Never raises: a corrupt PDF in an 11k run must not lose the other 11,323.
    The failure is recorded with its exception text instead.
    """
    started = time.perf_counter()
    try:
        with fitz.open(pdf_path) as doc:
            text = METHODS[method](doc)
            page_count = len(doc)
        status = "ok" if text.strip() else "empty"
        error = None
    except Exception as e:  # noqa: BLE001 — recorded, not swallowed
        text, page_count, status, error = "", None, "error", f"{type(e).__name__}: {e}"

    return {
        "text": text,
        "char_count": len(text),
        "status": status,
        "error": error,
        "page_count": page_count,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract text from corpus PDFs")
    parser.add_argument("--method", required=True, choices=sorted(METHODS))
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--limit", type=int, default=None, help="pilot on N reports")
    parser.add_argument(
        "--project", action="append", default=None,
        help="restrict to a GDC project, e.g. --project TCGA-LUAD (repeatable)",
    )
    parser.add_argument(
        "--force", action="store_true", help="redo reports already extracted"
    )
    args = parser.parse_args()

    conn = corpus_db.connect(args.db)

    # file_id is a random UUID, so ordering by it makes --limit an arbitrary
    # (not systematically biased) subset — adequate for a pilot.
    where, params = [], []
    if not args.force:
        where.append("t.file_id IS NULL")
    if args.project:
        where.append(f"r.project IN ({','.join('?' * len(args.project))})")
        params.extend(args.project)

    sql = (
        "SELECT r.file_id FROM report r "
        "LEFT JOIN report_text t ON t.file_id = r.file_id AND t.method = ?"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.file_id"

    rows = conn.execute(sql, [args.method, *params]).fetchall()

    if args.limit:
        rows = rows[: args.limit]

    total = len(rows)
    if not total:
        print(f"nothing to do for method={args.method} (use --force to redo)")
        return 0

    if args.method in OCR_METHODS:
        print(
            f"NOTE: {args.method} re-OCRs every page (~1.4s/report). "
            f"{total} reports is roughly {total * 1.4 / 3600:.1f}h. "
            f"The presence audit runs on embedded_sorted and does not need this."
        )

    print(f"extracting {total} reports with method={args.method}")
    counts = {"ok": 0, "empty": 0, "error": 0, "missing": 0}

    for i, row in enumerate(rows, start=1):
        file_id = row["file_id"]
        pdf_path = args.pdf_dir / f"{file_id}.pdf"

        if not pdf_path.exists():
            counts["missing"] += 1
            result = {
                "text": "", "char_count": 0, "status": "error",
                "error": f"PDF not found at {pdf_path}",
                "page_count": None, "elapsed_ms": 0,
            }
        else:
            result = extract_one(pdf_path, args.method)
            counts[result["status"]] += 1

        conn.execute(
            "INSERT OR REPLACE INTO report_text "
            "(file_id, method, text, char_count, status, error, elapsed_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, args.method, result["text"], result["char_count"],
             result["status"], result["error"], result["elapsed_ms"]),
        )
        if result["page_count"] is not None:
            conn.execute(
                "UPDATE report SET page_count = ? WHERE file_id = ?",
                (result["page_count"], file_id),
            )

        # Commit periodically so a crash mid-run does not discard hours of OCR.
        if i % 50 == 0:
            conn.commit()
            print(f"  {i}/{total}")

    record_tool_versions(conn, args.method)
    conn.commit()

    print(
        f"\ndone: ok={counts['ok']} empty={counts['empty']} "
        f"error={counts['error']} missing_pdf={counts['missing']}"
    )
    if counts["error"] or counts["missing"]:
        for r in conn.execute(
            "SELECT file_id, error FROM report_text "
            "WHERE method = ? AND status = 'error' LIMIT 10",
            (args.method,),
        ):
            print(f"  {r['file_id']}: {r['error']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
