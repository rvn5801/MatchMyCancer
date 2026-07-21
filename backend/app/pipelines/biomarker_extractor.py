"""LLM-powered biomarker extraction from clinical reports.

Uses langchain's with_structured_output() to force the LLM into producing
typed Pydantic objects rather than free text that needs parsing.

Key design decisions:
  - Temperature 0.0 for deterministic extraction (no creative variation)
  - System prompt is domain-specific — instructs the LLM as a precision
    oncology data extraction specialist
  - Only extracts what is explicitly stated — the "do not infer" rule
    is critical for clinical safety
  - raw_text field on every biomarker provides provenance back to the source
    document
"""

import logging
import re
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.models.biomarker import BiomarkerResult, ConfidenceTier

logger = logging.getLogger(__name__)


def _find_span(report_text: str, snippet: str) -> tuple[int, int] | None:
    """Find character span of snippet in report_text (case-insensitive, fuzzy)."""
    if not snippet:
        return None
    # Try exact match first
    idx = report_text.find(snippet)
    if idx >= 0:
        return (idx, idx + len(snippet))
    # Try case-insensitive
    m = re.search(re.escape(snippet), report_text, re.IGNORECASE)
    if m:
        return m.span()
    # Try first 50 chars of snippet
    short = snippet[:50]
    idx = report_text.find(short)
    if idx >= 0:
        return (idx, idx + len(short))
    m = re.search(re.escape(short), report_text, re.IGNORECASE)
    if m:
        return m.span()
    return None


# ── System prompt ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\\
You are a precision oncology data extraction specialist.

Your task: extract all clinically relevant biomarkers and molecular findings
from the medical report text provided by the user.

Rules:
1. ONLY extract what is explicitly stated — never infer, assume, or guess.
2. For every biomarker, capture the exact raw text that supports the finding
   in the 'raw_text' field.
3. Use standard HGNC gene symbols (EGFR, not epidermal growth factor receptor).
4. For alteration_type, use one of: mutation, amplification, fusion,
   deletion, expression, or leave null if unclear.
5. Capture MSI status (MSS, MSI-H, MSI-L) if reported.
6. Capture TMB (tumor mutational burden) as a number in mut/Mb if reported.
7. Capture PD-L1 score as stated (e.g. "TPS 80%", "CPS 5", "negative").
8. If no biomarkers are found, return an empty biomarkers list — do NOT
   fabricate findings.
"""

# ── LLM client (lazy singleton) ────────────────────────────────────────────

_llm: ChatOpenAI | None = None
_structured_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    """Get or create the LLM client, lazily initialized."""
    global _llm
    if _llm is None:
        if not settings.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. "
                "Set it in backend/.env or as an environment variable."
            )
        _llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.0,
            max_tokens=2000,
        )
    return _llm


def _get_structured_llm() -> ChatOpenAI:
    """Get or create the structured-output-configured LLM client."""
    global _structured_llm
    if _structured_llm is None:
        llm = _get_llm()
        _structured_llm = llm.with_structured_output(BiomarkerResult)
    return _structured_llm


# ── Public API ─────────────────────────────────────────────────────────────


def extract_biomarkers(report_text: str) -> BiomarkerResult:
    """Extract biomarkers from clinical report text.

    Args:
        report_text: Full text of a pathology, genomics, or molecular
            testing report.

    Returns:
        BiomarkerResult with extracted genes, alterations, MSI status,
        TMB, and PD-L1 score.

    Raises:
        RuntimeError: If OPENAI_API_KEY is not configured.
        ValueError: If report_text is empty.
    """
    if not report_text or not report_text.strip():
        raise ValueError("report_text must not be empty")

    logger.info(
        "Extracting biomarkers from report (%d chars)", len(report_text)
    )

    structured_llm = _get_structured_llm()

    try:
        result = structured_llm.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract biomarkers from:\n\n{report_text}"},
        ])
    except Exception as e:
        logger.error("Biomarker extraction failed: %s", e)
        raise

    # Add source spans for provenance + confidence tier
    for b in result.biomarkers:
        if b.raw_text and not b.source_span:
            b.source_span = _find_span(report_text, b.raw_text)
        # Assign confidence tier
        if b.source_span:
            start, end = b.source_span
            snippet = report_text[start:end]
            if snippet.lower() == b.raw_text.lower():
                b.confidence = ConfidenceTier.HIGHEST
            else:
                b.confidence = ConfidenceTier.MEDIUM
        else:
            b.confidence = ConfidenceTier.LOW

    logger.info(
        "Extracted %d biomarkers (MSI=%s, TMB=%s, PD-L1=%s)",
        len(result.biomarkers),
        result.msi_status,
        result.tmb,
        result.pd_l1_score,
    )

    return result