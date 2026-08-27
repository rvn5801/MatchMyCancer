"""LLM-powered cancer diagnosis extraction from clinical reports.

Extracts primary site, histology, stage, and grade from pathology
and clinical reports using structured LLM output.
"""

import logging
import re
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.models.biomarker import (
    CancerDiagnosis,
    ConfidenceTier,
    TumorInstance,
    TumorSet,
)

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

Extract EVERY distinct tumor described in this medical report. For each one:
- label: how the report identifies it, in the report's own words
  (e.g. "Right breast, 9 o'clock", "Part 3: left breast")
- primary_site: anatomic site where the cancer ORIGINATED (e.g., "lung", "breast", "skin")
- histology: histological type (e.g., "adenocarcinoma", "squamous cell carcinoma")
- stage: AJCC stage GROUP only (e.g., "Stage IV", "Stage IIIB") — never TNM
- tnm: TNM classification if reported, spaced (e.g., "pT4 pN2 M0")
- grade: tumor differentiation grade if reported
- laterality: left, right, or bilateral if specified
- tumor_size: largest dimension of the invasive component
- nodes_examined / nodes_positive: lymph node counts for THIS tumor
- lymphovascular_invasion: true if identified, false if explicitly absent
- margins: margin status as reported
- raw_text: a SHORT verbatim excerpt (at most 2-3 lines) that identifies this
  tumor — its diagnosis line, NOT the entire section. Long quotes get the
  output truncated.

Rules:
1. Only extract what is explicitly stated — never infer.
2. If a field is not mentioned, leave it null.
3. Use standard medical terminology (lowercase for site, standard histology names).
4. primary_site is the site of ORIGIN, not the site the specimen was taken from.
   A biopsy of a lymph node, liver, or other metastasis still has the primary
   site of the originating tumor. Melanoma found in an axillary node is
   primary_site "skin", not "axillary" or "lymph node". If the report gives
   only a metastatic specimen and never states the origin, leave it null.
5. Keep stage and TNM separate. "pT2 pN1 M0, Stage IIB" means
   stage="Stage IIB" and tnm="pT2 pN1 M0". If only TNM is reported, set
   tnm and leave stage null — do not put TNM in the stage field.
6. A bilateral case is TWO tumors, not one with laterality "bilateral".
   Separate any tumors that differ in size, grade, stage or node status.
   A satellite nodule of the same tumor is NOT a separate tumor.
   Lymph node counts belong to the tumor they drain — do not copy one
   tumor's node status onto another.
7. A report describing a single tumor returns a list with exactly one entry.
8. If the text does not describe any cancer or tumor, return an EMPTY tumors
   list. Never fabricate a tumor, and never copy the examples from these
   instructions into your output — "pT2 pN1 M0, Stage IIB" above is an
   example of formatting, not a finding.
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
            base_url=settings.openai_base_url or None,
            temperature=0.0,
            # TumorSet returns EVERY tumour with per-field values and raw_text
            # excerpts. At 1000 the tool-call JSON truncated mid-string on a
            # real 2-tumour report (unterminated string -> OutputParserException
            # -> HTTP 500 in production).
            max_tokens=4000,
        )
    return _llm


def _get_structured_llm() -> ChatOpenAI:
    global _structured_llm
    if _structured_llm is None:
        _structured_llm = _get_llm().with_structured_output(TumorSet)
    return _structured_llm


def _size_mm(size: str | None) -> float:
    """Parse a reported size to millimetres for comparison. 0.0 if unparseable."""
    if not size:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mm|cm)", size, re.IGNORECASE)
    if not m:
        return 0.0
    value = float(m.group(1))
    return value * 10 if m.group(2).lower() == "cm" else value


def dominant_tumor(tumors: list[TumorInstance]) -> TumorInstance | None:
    """Pick the tumour that should drive trial and therapy matching.

    Node-positive disease outranks node-negative, then larger outranks smaller.
    On TCGA-BH-A18H the first-listed tumour is the right breast (pT1b pN0,
    0/1 nodes) while the clinically driving disease is the left (pT1c pN1a,
    2/24 nodes) — taking the first entry would query trials for the wrong one.

    ponytail: two signals, no stage-group parsing. Add AJCC ordering if a case
    turns up where node status and size disagree with the stage group.
    """
    if not tumors:
        return None
    return max(
        tumors,
        key=lambda t: (t.nodes_positive or 0, _size_mm(t.tumor_size)),
    )


def _as_diagnosis(tumor: TumorInstance) -> CancerDiagnosis:
    """Flatten one tumour to the legacy single-diagnosis shape."""
    return CancerDiagnosis(
        primary_site=tumor.primary_site,
        histology=tumor.histology,
        stage=tumor.stage,
        tnm=tumor.tnm,
        grade=tumor.grade,
        laterality=tumor.laterality,
        raw_text=tumor.raw_text,
        source_span=tumor.source_span,
        confidence=tumor.confidence,
    )


def extract_tumors(report_text: str) -> list[TumorInstance]:
    """Extract every distinct tumour described in a report.

    Args:
        report_text: Clinical or pathology report text.

    Returns:
        One TumorInstance per tumour. Empty if none could be extracted.

    Raises:
        RuntimeError: If OPENAI_API_KEY is not configured.
        ValueError: If report_text is empty.
    """
    if not report_text or not report_text.strip():
        raise ValueError("report_text must not be empty")

    logger.info("Extracting tumours from report (%d chars)", len(report_text))

    result = _get_structured_llm().invoke([
        {"role": "system", "content": DIAGNOSIS_PROMPT},
        {"role": "user", "content": report_text},
    ])

    for tumor in result.tumors:
        if tumor.raw_text and not tumor.source_span:
            tumor.source_span = _find_span(report_text, tumor.raw_text)
        if tumor.source_span:
            start, end = tumor.source_span
            snippet = report_text[start:end]
            tumor.confidence = (
                ConfidenceTier.HIGHEST
                if snippet.lower() == tumor.raw_text.lower()
                else ConfidenceTier.MEDIUM
            )
        else:
            tumor.confidence = ConfidenceTier.LOW

    # Fabrication guard. Fed "The weather is nice today.", the model returned
    # a complete breast cancer diagnosis copied from this prompt's own example.
    # A tumour none of whose extracted values appear anywhere in the document
    # is not evidence — it is invented, and it must not reach a patient.
    def _has_evidence(t: TumorInstance) -> bool:
        if t.source_span:
            return True
        lower = report_text.lower()
        return any(
            value and value.lower() in lower
            for value in (t.histology, t.tnm, t.primary_site)
        )

    fabricated = [t for t in result.tumors if not _has_evidence(t)]
    if fabricated:
        logger.warning(
            "Dropped %d tumour(s) with no textual evidence in the document: %s",
            len(fabricated),
            "; ".join(f"{t.label} [{t.histology or '?'}]" for t in fabricated),
        )
        result.tumors = [t for t in result.tumors if _has_evidence(t)]

    logger.info(
        "Extracted %d tumour(s): %s",
        len(result.tumors),
        "; ".join(
            f"{t.label} [{t.primary_site or '?'} {t.histology or '?'} "
            f"{t.tnm or t.stage or 'unstaged'}]"
            for t in result.tumors
        ) or "none",
    )

    return result.tumors


def extract_diagnosis(report_text: str) -> CancerDiagnosis | None:
    """Extract the dominant tumour as a single diagnosis.

    Kept for consumers that expect one diagnosis (trial condition query,
    evaluator). Callers that need the full picture should use extract_tumors.
    """
    tumors = extract_tumors(report_text)
    dominant = dominant_tumor(tumors)
    return _as_diagnosis(dominant) if dominant else None