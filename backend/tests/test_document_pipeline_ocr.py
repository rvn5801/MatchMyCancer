"""Tests for the scanned-PDF OCR path.

Regression guard: OCR used to read only page 1 (`doc[0]`) while reporting
success, silently discarding later pages. Measured on a real 2-page TCGA
pathology report, that dropped ~45% of the text and turned a correct
stage/histology extraction into nulls.
"""

import fitz
import pytest

from app.pipelines import document_pipeline
from app.pipelines.document_pipeline import MAX_OCR_PAGES, process_document


def _image_only_pdf(page_texts: list[str]) -> bytes:
    """Build a PDF whose pages are images — no extractable text layer."""
    text_doc = fitz.open()
    for text in page_texts:
        page = text_doc.new_page()
        page.insert_text((72, 100), text, fontsize=22)

    scanned = fitz.open()
    for page in text_doc:
        pix = page.get_pixmap(dpi=150)
        new = scanned.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(page.rect, stream=pix.tobytes("png"))

    data = scanned.tobytes()
    scanned.close()
    text_doc.close()
    return data


def test_image_only_pdf_has_no_text_layer():
    """Guard the fixture itself — if a text layer leaks in, OCR never runs."""
    pdf = _image_only_pdf(["PAGE ONE"])
    doc = fitz.open(stream=pdf, filetype="pdf")
    assert doc[0].get_text().strip() == ""
    doc.close()


def test_ocr_reads_every_page(monkeypatch):
    """All pages must be OCR'd, not just the first."""
    seen = []

    def fake_ocr(img_bytes):
        seen.append(img_bytes)
        return {"text": f"PAGE{len(seen)}", "confidence": 0.9}

    monkeypatch.setattr(document_pipeline, "ocr_image", fake_ocr)

    result = process_document(_image_only_pdf(["one", "two", "three"]),
                              "application/pdf")

    assert len(seen) == 3, "OCR should run on every page"
    assert result["page_count"] == 3
    for marker in ("PAGE1", "PAGE2", "PAGE3"):
        assert marker in result["full_text"]


def test_ocr_confidence_is_the_weakest_page(monkeypatch):
    """One unreadable page must not be hidden by good pages."""
    scores = iter([0.9, 0.3, 0.8])
    monkeypatch.setattr(
        document_pipeline, "ocr_image",
        lambda _b: {"text": "text", "confidence": next(scores)},
    )

    result = process_document(_image_only_pdf(["a", "b", "c"]), "application/pdf")
    assert result["confidence"] == pytest.approx(0.3)


def test_ocr_page_cap_is_enforced(monkeypatch):
    """A long scan must not block the request unbounded."""
    calls = []
    monkeypatch.setattr(
        document_pipeline, "ocr_image",
        lambda _b: (calls.append(1), {"text": "x", "confidence": 0.9})[1],
    )

    pdf = _image_only_pdf(["p"] * (MAX_OCR_PAGES + 3))
    result = process_document(pdf, "application/pdf")

    assert len(calls) == MAX_OCR_PAGES
    assert result["page_count"] == MAX_OCR_PAGES


def test_text_layer_pdf_skips_ocr(monkeypatch):
    """OCR is the fallback — a text PDF must never pay for it."""
    def boom(_b):
        raise AssertionError("OCR should not run on a text-layer PDF")

    monkeypatch.setattr(document_pipeline, "ocr_image", boom)

    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "Lung adenocarcinoma, Stage IIIB")
    data = doc.tobytes()
    doc.close()

    result = process_document(data, "application/pdf")
    assert result["extraction_method"] == "pymupdf"
    assert "adenocarcinoma" in result["full_text"]
