"""SQLite store for the TCGA pathology report corpus.

One file holds every stage's output, so the presence audit is a query rather
than a pipeline of intermediate files. Stages are independently re-runnable:
changing the matcher must not require re-downloading 3 GB or re-running hours
of OCR.

ponytail: sqlite3 is stdlib and 11k rows is nothing. Reach for a real database
only if this needs concurrent writers, which a single-user research tool does not.
"""

import sqlite3
from pathlib import Path
from typing import Any, Optional

DEFAULT_DB = Path(__file__).parent / "corpus.db"

SCHEMA = """
-- One row per PDF. Keyed on file_id, NOT barcode: TCGA has more pathology
-- report files than cases, so some patients have several reports and keying
-- on barcode would silently drop them.
CREATE TABLE IF NOT EXISTS report (
  file_id    TEXT PRIMARY KEY,
  barcode    TEXT NOT NULL,
  project    TEXT NOT NULL,
  filename   TEXT NOT NULL,
  page_count INTEGER
);
CREATE INDEX IF NOT EXISTS idx_report_barcode ON report(barcode);

-- One row per (report, extraction method). `status` is required: a missing row
-- must not mean both "not run yet" and "failed" — ambiguous absence is how an
-- evaluation harness ends up reporting confident numbers while testing nothing.
CREATE TABLE IF NOT EXISTS report_text (
  file_id    TEXT NOT NULL REFERENCES report(file_id),
  method     TEXT NOT NULL,
  text       TEXT NOT NULL,
  char_count INTEGER NOT NULL,
  status     TEXT NOT NULL,
  error      TEXT,
  elapsed_ms INTEGER,
  PRIMARY KEY (file_id, method)
);

-- Clinical labels from cBioPortal, per patient. Sample-level attributes are
-- collapsed to the primary tumour sample before landing here.
CREATE TABLE IF NOT EXISTS label (
  barcode   TEXT NOT NULL,
  attribute TEXT NOT NULL,
  value     TEXT NOT NULL,
  PRIMARY KEY (barcode, attribute)
);

-- The study output. matched_span holds the ORIGINAL document text that matched,
-- so every counted match is inspectable rather than taken on trust.
CREATE TABLE IF NOT EXISTS presence (
  file_id      TEXT NOT NULL,
  attribute    TEXT NOT NULL,
  method       TEXT NOT NULL,
  strictness   TEXT NOT NULL,
  found        INTEGER NOT NULL,
  matched_span TEXT,
  PRIMARY KEY (file_id, attribute, method, strictness)
);

-- Provenance. A result is not reproducible without tool versions and fetch dates.
CREATE TABLE IF NOT EXISTS run_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Open the corpus database, creating the schema if absent."""
    db_path = Path(path) if path else DEFAULT_DB
    if db_path != Path(":memory:"):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO run_meta (key, value) VALUES (?, ?)",
        (key, str(value)),
    )


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM run_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None
