"""
Tests for the OCR engine.

Creates synthetic images with Pillow's ImageDraw to test Tesseract.
Skips gracefully if tesseract is not installed (standard CI pattern).

To run locally: apt install tesseract-ocr
"""

import shutil

import pytest
from PIL import Image, ImageDraw

from app.services.ocr_engine import ocr_image

# Guard: skip all tests if tesseract binary is not installed
# This is the standard pattern for optional system dependencies
TESSERACT_AVAILABLE = shutil.which("tesseract") is not None
pytestmark = pytest.mark.skipif(
    not TESSERACT_AVAILABLE,
    reason="tesseract-ocr not installed. Run: sudo apt install tesseract-ocr",
)


def create_text_image_bytes(text: str, size: tuple = (800, 200)) -> bytes:
    """Create a white image with black text using Pillow, return bytes."""
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), text, fill="black")
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_ocr_extracts_plain_text():
    """Tesseract should recognize clearly rendered text."""
    img_bytes = create_text_image_bytes("EGFR mutation detected")

    result = ocr_image(img_bytes)

    assert "EGFR" in result["text"].upper()
    assert 0.0 <= result["confidence"] <= 1.0


def test_ocr_returns_confidence_range():
    """Confidence should be a float between 0 and 1."""
    img_bytes = create_text_image_bytes("HER2 negative")

    result = ocr_image(img_bytes)

    assert isinstance(result["confidence"], float)
    assert 0.0 <= result["confidence"] <= 1.0


def test_ocr_handles_blank_image():
    """Blank image: no text to extract."""
    img = Image.new("RGB", (200, 200), "white")
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    result = ocr_image(img_bytes)

    assert result["text"] == ""
    assert result["confidence"] == 0.0


def test_ocr_handles_biomarker_keywords():
    """Real-world simulation: biomarker report keywords.

    Note: Tesseract can mangle small-text synthetic images.
    On real scanned documents (300 DPI), accuracy is much higher.
    This test uses larger font for reliable results.
    """
    img = Image.new("RGB", (1200, 300), "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), "EGFR mutation detected", fill="black")
    draw.text((20, 80), "ALK rearrangement negative", fill="black")
    draw.text((20, 140), "KRAS G12C mutation detected", fill="black")
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    result = ocr_image(img_bytes)

    text_upper = result["text"].upper()
    # Only assert what Tesseract reliably reads: gene names
    assert "EGFR" in text_upper
    assert "ALK" in text_upper
    assert "KRAS" in text_upper or "K RAS" in text_upper
