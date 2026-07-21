"""
PDF text extraction service.

Uses PyMuPDF (imported as `fitz`) — the Python binding for MuPDF,
an open-source C library that powers many PDF readers.

Why PyMuPDF over alternatives:
- PyPDF2: Pure Python, 10-50x slower, fails on complex PDFs
- pdfplumber: Good at tables but overkill for text extraction
- fitz: Fast (C engine), handles text + images, gives font info,
  and can detect whether a page is text or scanned

The name "fitz" is historical — PyMuPDF originally wrapped
the Fitz library before MuPDF replaced it. The alias stuck.
"""

import fitz  # PyMuPDF
from typing import Any


def extract_pdf_text(file_bytes: bytes) -> dict[str, Any]:
    """
    Extract text from every page of a PDF.

    Returns a structured dict, not just a string. Why?
    1. Downstream code may need per-page access (biomarker on p.3)
    2. The UI can show "Processing page 3 of 15"
    3. Page-level extraction confidence can vary (p.2 is text,
       p.3 is a scanned image — but that's T8's job)

    Args:
        file_bytes: PDF content as bytes

    Returns:
        {
            "full_text": "All pages concatenated with double newlines",
            "page_count": 15,
            "pages": [
                {"page_num": 1, "text": "Page 1 content..."},
                {"page_num": 2, "text": "Page 2 content..."},
            ]
        }
    """
    # fitz.open() with stream= accepts bytes directly
    doc = fitz.open(stream=file_bytes, filetype="pdf")

    pages: list[dict[str, Any]] = []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text()
        pages.append({"page_num": page_num, "text": text})

    # Always close explicitly. fitz uses C memory allocations.
    # Python's garbage collector may not free them promptly.
    doc.close()

    full_text = "\n\n".join(p["text"] for p in pages)

    return {
        "full_text": full_text,
        "page_count": len(pages),
        "pages": pages,
    }
