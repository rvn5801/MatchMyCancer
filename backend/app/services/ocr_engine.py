"""
OCR engine using Tesseract.

Architecture note:
pytesseract is a subprocess wrapper, not a native Python library.
It shells out to the `tesseract` CLI binary. This means:
1. tesseract-ocr must be installed at the SYSTEM level (apt install)
2. It writes temp files for every call (the image and output)
3. It's single-threaded — for batch processing, use multiprocessing
4. Language data lives in /usr/share/tesseract-ocr/4.00/tessdata/

For production: consider running tesseract as a persistent daemon
(tesserocr library wraps the C++ API for ~3x faster inference).
But for v1, pytesseract is simpler and sufficient.
"""

import tempfile
from pathlib import Path
from typing import Any

import pytesseract


def ocr_image(image_bytes: bytes) -> dict[str, Any]:
    """
    Run Tesseract OCR on an image.

    Args:
        image_bytes: Image content as bytes (PNG, JPEG, TIFF)

    Returns:
        {
            "text": "Extracted text from the image",
            "confidence": float  # mean confidence of all words
        }
    """
    # Write image to temp file (tesseract CLI needs a path)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    try:
        # Run tesseract — detailed output includes confidence
        data = pytesseract.image_to_data(
            tmp_path,
            output_type=pytesseract.Output.DICT,
            config="--psm 6",  # Assume single uniform block of text
        )

        # Extract text and confidence
        words = [
            data["text"][i]
            for i in range(len(data["text"]))
            if data["text"][i].strip()
        ]
        confidences = [
            data["conf"][i]
            for i in range(len(data["conf"]))
            if data["text"][i].strip()
        ]

        text = " ".join(words)
        avg_confidence = sum(confidences) / len(confidences) / 100.0 if confidences else 0.0

        return {
            "text": text,
            "confidence": round(avg_confidence, 3),
        }
    finally:
        Path(tmp_path).unlink(missing_ok=True)
