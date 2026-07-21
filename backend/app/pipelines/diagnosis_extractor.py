"""LLM-powered cancer diagnosis extraction from clinical reports.

Extracts primary site, histology, stage, and grade from pathology
and clinical reports using structured LLM output.
"""

import logging
import re
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.models.biomarker import CancerDiagnosis, ConfidenceTier

logger = logging.getLogger(__name__)


def _find_span(report_text: str, snippet: str) -> tuple[int, int] | None:
    """Find character span of snippet in report_text (case-insensitive, fuzzy)."""
    if not snippet:
        return None
    idx = report_text.find(snippet)
    if idx >= 0:
        return (idx, idx + len(snippet))
    m = re.search(re.escape(snippet), report_text, re.IGNORECASE)
    if m:
        return m.span()
    short = snippet[:50]
    idx = report_text.find(short)
    if idx >= 0:
        return (idx, idx + len(short))
    m = re.search(re.escape(short), report_text, re.IGNORECASE)
    if m:
        return m.span()
    return None


DIAGNOSIS_PROMPT = """\\
You are an oncology data extraction specialist.

Extract the cancer diagnosis from this medical report. Include:
- primary_site: anatomic site (e.g., "lung", "breast", "colon")
- histology: histological type (e.g., "adenocarcinoma", "squamous cell carcinoma")
- stage: AJCC stage or other staging if reported (e.g., "Stage IV", "T2N1M0")
- grade: tumor differentiation grade if reported
- laterality: left, right, or bilateral if specified
- raw_text: the exact text from the report that supports the diagnosis

Rules:
1. Only extract what is explicitly stated — never infer.
2. If a field is not mentioned, leave it null.
3. Use standard medical terminology (lowercase for site, standard histology names).
"""

_llm: ChatOpenAI | None = None
_structured_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        _llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.0,
            max_tokens=1000,
        )
    return _llm


def _get_structured_llm() -> ChatOpenAI:
    global _structured_llm
    if _structured_llm is None:
        _structured_llm = _get_llm().with_structured_output(CancerDiagnosis)
    return _structured_llm


def extract_diagnosis(report_text: str) -> CancerDiagnosis:
    """Extract cancer diagnosis from report text.

    Args:
        report_text: Clinical or pathology report text.

    Returns:
        CancerDiagnosis with primary site, histology, stage, grade.

    Raises:
        RuntimeError: If OPENAI_API_KEY is not configured.
        ValueError: If report_text is empty.
    """
    if not report_text or not report_text.strip():
        raise ValueError("report_text must not be empty")

    logger.info("Extracting diagnosis from report (%d chars)", len(report_text))

    structured_llm = _get_structured_llm()
    result = structured_llm.invoke([
        {"role": "system", "content": DIAGNOSIS_PROMPT},
        {"role": "user", "content": report_text},
    ])

    logger.info(
        "Diagnosis: %s %s (%s)",
        result.primary_site or "?",
        result.histology or "?",
        result.stage or "no stage",
    )

    # Add source span + confidence
    if result.raw_text and not result.source_span:
        result.source_span = _find_span(report_text, result.raw_text)
    if result.source_span:
        start, end = result.source_span
        snippet = report_text[start:end]
        if snippet.lower() == result.raw_text.lower():
            result.confidence = ConfidenceTier.HIGHEST
        else:
            result.confidence = ConfidenceTier.MEDIUM
    else:
        result.confidence = ConfidenceTier.LOW

    return result