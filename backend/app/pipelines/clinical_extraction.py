"""Unified clinical extraction pipeline.

Combines biomarker extraction and diagnosis extraction into a single
call that produces a complete ClinicalExtraction from document text.

This is what the API endpoint calls — consumers don't need to know
about the individual extractors.
"""

import logging
from typing import Dict, Any

from app.models.biomarker import ClinicalExtraction
from app.pipelines.biomarker_extractor import extract_biomarkers
from app.pipelines.diagnosis_extractor import extract_diagnosis

logger = logging.getLogger(__name__)


def extract_clinical_data(document_text: str) -> ClinicalExtraction:
    """Run full clinical extraction on document text.

    Extracts both biomarkers and diagnosis in two LLM calls, then
    combines them into a single ClinicalExtraction.

    Args:
        document_text: Full text from a processed document (PDF extraction
            or OCR output).

    Returns:
        ClinicalExtraction with biomarkers, diagnosis, and source text.

    Raises:
        RuntimeError: If OPENAI_API_KEY is not configured.
        ValueError: If document_text is empty.
    """
    if not document_text or not document_text.strip():
        raise ValueError("document_text must not be empty")

    logger.info("Starting clinical extraction (%d chars)", len(document_text))

    biomarkers = extract_biomarkers(document_text)
    diagnosis = extract_diagnosis(document_text)

    result = ClinicalExtraction(
        biomarkers=biomarkers,
        diagnosis=diagnosis,
        raw_report_text=document_text[:2000],
    )

    logger.info(
        "Clinical extraction complete: %d biomarkers, diagnosis=%s %s",
        len(biomarkers.biomarkers),
        diagnosis.primary_site or "?",
        diagnosis.histology or "?",
    )

    return result


def process_and_extract(document_result: Dict[str, Any]) -> ClinicalExtraction:
    """Process a document pipeline result and extract clinical data.

    This bridges the gap between Phase 2's document processing pipeline
    output and Phase 3's clinical extraction. Takes the dict returned
    by document_pipeline.process_document() and runs extraction on the
    full_text.

    Args:
        document_result: Dict from process_document() containing
            'full_text' key.

    Returns:
        ClinicalExtraction result.

    Raises:
        ValueError: If no text was extracted from the document.
    """
    text = document_result.get("full_text", "")
    if not text.strip():
        raise ValueError("No text extracted from document")

    logger.info(
        "Processing document output: method=%s, pages=%d",
        document_result.get("extraction_method", "unknown"),
        document_result.get("page_count", 0),
    )

    return extract_clinical_data(text)
