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


# OCR runs ~1-3s per page and blocks the request, so cap the work.
# ponytail: fixed cap, no partial/async processing. Raise it or move OCR to a
# background job if long scanned reports become common.
MAX_OCR_PAGES = 10


def _ocr_pdf(pdf_bytes: bytes) -> dict[str, Any] | None:
    """OCR a scanned PDF by rendering each page as an image.

    Every page is processed, not just the first: molecular addenda and
    staging summaries routinely sit on later pages, and OCR'ing only page 1
    silently discards them while still reporting success.

    Returns the standard pipeline result dict on success, or None
    if rendering/OCR fails.
    """
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        pages_to_read = min(total_pages, MAX_OCR_PAGES)

        texts: list[str] = []
        confidences: list[float] = []
        for i in range(pages_to_read):
            pix = doc[i].get_pixmap(dpi=200)
            page_result = ocr_image(pix.tobytes("png"))
            if page_result["text"].strip():
                texts.append(page_result["text"])
            if page_result.get("confidence") is not None:
                confidences.append(page_result["confidence"])
        doc.close()

        if total_pages > pages_to_read:
            logger.warning(
                "PDF has %d pages — OCR limited to the first %d",
                total_pages, pages_to_read,
            )

        full_text = "\n\n".join(texts)
        return {
            "full_text": full_text,
            "page_count": pages_to_read,
            "extraction_method": "tesseract (from PDF image)",
            # Weakest page drives the score — one unreadable page can hide
            # the finding that matters.
            "confidence": min(confidences) if confidences else None,
            "status": "success" if full_text.strip() else "low_text",
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
        logger.info("PDF has no extractable text — trying OCR on all pages")
        ocr_result = _ocr_pdf(file_bytes)
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
