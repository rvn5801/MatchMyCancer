"""Unified document processing pipeline.

Implements the Strategy Pattern:
- Every document type has its own extraction strategy
- All strategies return the SAME output shape
- The caller (upload endpoint) doesn't know or care which strategy ran

Adding a new format (e.g., DICOM, Word doc) means:
1. Write a new extractor function in services/
2. Add a route in this file's process_document()
3. Done. No changes to any existing code.

For scanned/image-based PDFs: PyMuPDF text extraction returns empty.
We fall back by rendering the first page as an image and running OCR.
"""

import logging
from typing import Any

from app.services.ocr_engine import ocr_image
from app.services.pdf_extractor import extract_pdf_text

logger = logging.getLogger(__name__)


def _ocr_pdf_first_page(pdf_bytes: bytes) -> dict[str, Any] | None:
    """Try OCR on the first page of a PDF by rendering it as an image.

    Returns the standard pipeline result dict on success, or None
    if rendering/OCR fails.
    """
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        doc.close()

        ocr_result = ocr_image(img_bytes)

        return {
            "full_text": ocr_result["text"],
            "page_count": 1,
            "extraction_method": "tesseract (from PDF image)",
            "confidence": ocr_result["confidence"],
            "status": "success" if ocr_result["text"].strip() else "low_text",
        }
    except Exception as e:
        logger.warning("OCR fallback for PDF failed: %s", e)
        return None


def process_document(file_bytes: bytes, content_type: str) -> dict[str, Any]:
    """Route a document to the correct extraction strategy.

    All strategies return the same shape:
    {
        "full_text": str,
        "page_count": int,
        "extraction_method": "pymupdf" | "tesseract" | "tesseract (from PDF image)",
        "confidence": float | None,
        "status": "success" | "low_text" | "error",
        "message": str | None,
    }
    """
    # === PDF: could be text-native or scanned ===
    if content_type == "application/pdf":
        result = extract_pdf_text(file_bytes)

        # Text-based PDF — direct extraction works
        if result["full_text"].strip():
            return {
                **result,
                "extraction_method": "pymupdf",
                "confidence": None,
                "status": "success",
            }

        # Image-based (scanned) PDF — fall back to OCR
        logger.info("PDF has no extractable text — trying OCR on page 1")
        ocr_result = _ocr_pdf_first_page(file_bytes)
        if ocr_result:
            return ocr_result

        # Both methods failed
        return {
            **result,
            "extraction_method": "none",
            "confidence": 0.0,
            "status": "low_text",
            "message": (
                "This PDF contains no extractable text and OCR failed. "
                "It may be a scanned document with low-quality images."
            ),
        }

    # === Images: OCR via Tesseract ===
    if content_type in ("image/jpeg", "image/png", "image/tiff"):
        ocr_result = ocr_image(file_bytes)
        return {
            "full_text": ocr_result["text"],
            "page_count": 1,
            "extraction_method": "tesseract",
            "confidence": ocr_result["confidence"],
            "status": "success" if ocr_result["text"].strip() else "low_text",
        }

    # === Unknown ===
    return {
        "full_text": "",
        "page_count": 0,
        "extraction_method": "none",
        "confidence": None,
        "status": "error",
        "message": f"Unsupported content type: {content_type}",
    }
