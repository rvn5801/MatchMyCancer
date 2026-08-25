"""Tests for corpus text extraction.

The value of keeping several methods side by side is that they disagree, so
these assert the methods are genuinely distinct and that failures are recorded
rather than lost.
"""

import fitz
import pytest

from app.evaluation import extract_text
from app.evaluation.extract_text import METHODS, extract_one


def _text_pdf(path, lines):
    doc = fitz.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 100 + i * 24), line, fontsize=11)
    doc.save(path)
    doc.close()


class TestExtractOne:
    def test_embedded_reads_text_layer(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        _text_pdf(pdf, ["FINAL DIAGNOSIS:", "Lung adenocarcinoma, Stage IIIB"])

        result = extract_one(pdf, "embedded")

        assert result["status"] == "ok"
        assert "adenocarcinoma" in result["text"]
        assert result["page_count"] == 1
        assert result["char_count"] == len(result["text"])

    def test_sorted_method_also_reads_text(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        _text_pdf(pdf, ["HISTOLOGIC GRADE:", "G3"])

        result = extract_one(pdf, "embedded_sorted")

        assert result["status"] == "ok"
        assert "G3" in result["text"]

    def test_corrupt_pdf_is_recorded_not_raised(self, tmp_path):
        """One bad file in an 11k run must not lose the other 11,323."""
        pdf = tmp_path / "broken.pdf"
        pdf.write_bytes(b"this is not a pdf")

        result = extract_one(pdf, "embedded")

        assert result["status"] == "error"
        assert result["error"]
        assert result["text"] == ""
        assert result["page_count"] is None

    def test_empty_page_reports_empty_not_ok(self, tmp_path):
        """'empty' and 'error' must stay distinguishable from 'not run'."""
        pdf = tmp_path / "blank.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(pdf)
        doc.close()

        assert extract_one(pdf, "embedded")["status"] == "empty"

    def test_elapsed_ms_is_recorded(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        _text_pdf(pdf, ["x"])
        assert extract_one(pdf, "embedded")["elapsed_ms"] >= 0

    def test_tesseract_method_uses_ocr_engine(self, tmp_path, monkeypatch):
        """tesseract5 must ignore the embedded layer and rasterise instead."""
        seen = []

        def fake_ocr(img_bytes):
            seen.append(img_bytes)
            return {"text": "OCR OUTPUT", "confidence": 0.9}

        monkeypatch.setattr(extract_text, "ocr_image", fake_ocr)

        pdf = tmp_path / "a.pdf"
        _text_pdf(pdf, ["EMBEDDED LAYER TEXT"])
        result = extract_one(pdf, "tesseract5")

        assert len(seen) == 1, "should rasterise every page"
        assert result["text"] == "OCR OUTPUT"
        assert "EMBEDDED" not in result["text"]

    def test_tesseract_reads_every_page(self, tmp_path, monkeypatch):
        """No page cap here — truncating would bias the presence audit."""
        calls = []
        monkeypatch.setattr(
            extract_text, "ocr_image",
            lambda _b: (calls.append(1), {"text": "p", "confidence": 0.9})[1],
        )

        pdf = tmp_path / "many.pdf"
        doc = fitz.open()
        for _ in range(15):
            doc.new_page()
        doc.save(pdf)
        doc.close()

        extract_one(pdf, "tesseract5")
        assert len(calls) == 15


class TestMethodRegistry:
    def test_all_methods_are_callable(self):
        assert set(METHODS) == {"embedded", "embedded_sorted", "tesseract5"}
        assert all(callable(fn) for fn in METHODS.values())

    def test_sorted_and_unsorted_can_differ(self, tmp_path):
        """The reading-order ablation only means something if the two differ.

        Text placed bottom-to-top in content-stream order comes back in that
        order unsorted, and top-to-bottom when sorted.
        """
        pdf = tmp_path / "order.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 700), "BOTTOM", fontsize=11)
        page.insert_text((72, 100), "TOP", fontsize=11)
        doc.save(pdf)
        doc.close()

        plain = extract_one(pdf, "embedded")["text"]
        sorted_ = extract_one(pdf, "embedded_sorted")["text"]

        assert plain.index("BOTTOM") < plain.index("TOP")
        assert sorted_.index("TOP") < sorted_.index("BOTTOM")
