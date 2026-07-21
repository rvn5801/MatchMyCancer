"""
Tests for the PDF text extractor.

Uses fitz (PyMuPDF) to create real PDFs in-memory during tests.
This is better than committing test fixture files because:
1. Tests are self-contained — no external dependencies
2. You can test specific PDF structures (single page, multi-page,
   empty, scanned-only)
3. No binary files in git
"""

import fitz  # PyMuPDF
from app.services.pdf_extractor import extract_pdf_text


def create_test_pdf_bytes(pages_text: list[str]) -> bytes:
    """Helper: create a PDF with given text on each page, return bytes."""
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((50, 50), text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_extracts_text_from_single_page():
    """Happy path: extract text from a one-page PDF."""
    pdf_bytes = create_test_pdf_bytes(["Patient has EGFR mutation."])

    result = extract_pdf_text(pdf_bytes)

    assert result["page_count"] == 1
    assert "EGFR" in result["full_text"]
    assert len(result["pages"]) == 1
    assert result["pages"][0]["page_num"] == 1


def test_extracts_text_from_multiple_pages():
    """Multi-page PDF: verify page count and concatenation."""
    pdf_bytes = create_test_pdf_bytes(
        ["Page one content", "Page two content", "Page three"]
    )

    result = extract_pdf_text(pdf_bytes)

    assert result["page_count"] == 3
    assert len(result["pages"]) == 3
    # Pages are separated by double newlines
    assert "\n\n" in result["full_text"]
    assert result["pages"][1]["page_num"] == 2
    assert "Page two" in result["pages"][1]["text"]


def test_handles_empty_page_pdf():
    """Edge case: PDF with a page that has no text (blank page)."""
    doc = fitz.open()
    doc.new_page()  # must have at least 1 page to save
    pdf_bytes = doc.tobytes()
    doc.close()

    result = extract_pdf_text(pdf_bytes)

    assert result["page_count"] == 1
    assert result["full_text"].strip() == ""  # blank page = no text


def test_returns_structured_biomarker_text():
    """Real-world simulation: text matching a pathology report format."""
    report = (
        "PATHOLOGY REPORT\n"
        "Diagnosis: Invasive ductal carcinoma\n"
        "ER: Positive (90%)\n"
        "HER2: Negative (IHC 1+)\n"
        "PIK3CA H1047R mutation detected\n"
    )
    pdf_bytes = create_test_pdf_bytes([report])

    result = extract_pdf_text(pdf_bytes)

    assert "PIK3CA" in result["full_text"]
    assert "HER2" in result["full_text"]
    assert "Diagnosis" in result["full_text"]
