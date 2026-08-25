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
9. Set 'result' on EVERY biomarker. This drives therapy matching, and a wrong
   or missing value can recommend a drug the patient must not receive:
     - 'positive'   — variant detected, amplified, or expression positive
     - 'negative'   — explicitly absent, not amplified, wild-type, or IHC 0/1+
     - 'equivocal'  — borderline with no confirmatory test performed
     - 'not_tested' — the report states this marker was NOT assessed
     - 'unknown'    — only when the report genuinely does not say
   Resolve reflex testing rather than reporting the intermediate result:
   "HER2/neu: IHC 2+, FISH not amplified" is 'negative'.
   A detected genomic variant (e.g. BRAF V600E) is 'positive'.
   'not_tested' and 'negative' are opposites — never substitute one for the other.
10. Record 'significance' verbatim when the report states it (pathogenic, likely
   pathogenic, variant of unknown significance, benign). A detected variant of
   unknown significance is still 'positive' with significance recorded — the
   downstream matcher uses significance to decide treatability.
11. Report each tumour's biomarkers separately when a report covers more than
   one specimen or laterality. Do NOT merge or drop repeated markers — two
   tumours each having an ER result is two findings, not one.
"""

# Appended when the tumour pass has already run. Two independent LLM calls
# invent different wording for the same specimen — measured on TCGA-BH-A18H,
# the tumour pass produced "Right breast, 9 o'clock" and the biomarker pass
# "Part 1: Right breast, 9 o'clock", so an exact join found nothing. Handing
# the second pass a fixed vocabulary removes the mismatch by construction.
LABEL_VOCABULARY_PROMPT = """\\

This report describes the following tumors:
{labels}

Assign every biomarker to exactly one of them by copying that label VERBATIM
into 'tumor_label'. Do not invent, abbreviate or reword labels. If a result
genuinely cannot be assigned to one of these tumors, leave tumor_label null
rather than guessing — a receptor result attributed to the wrong specimen is a
clinical error, an unattributed one is only an inconvenience.
"""


def _resolve_label(returned: str | None, known: list[str]) -> str | None:
    """Snap an extracted label onto the known tumour vocabulary.

    Exact match first, then unambiguous containment as a safety net for when
    the model paraphrases anyway. Ambiguous matches return None for the same
    reason the prompt says to: wrong attribution is worse than none.
    """
    if not returned or not known:
        return returned

    def norm(s: str) -> str:
        return " ".join(s.lower().split())

    target = norm(returned)
    for label in known:
        if norm(label) == target:
            return label

    matches = [l for l in known if norm(l) in target or target in norm(l)]
    return matches[0] if len(matches) == 1 else None

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


def extract_biomarkers(
    report_text: str, tumor_labels: list[str] | None = None
) -> BiomarkerResult:
    """Extract biomarkers from clinical report text.

    Args:
        report_text: Full text of a pathology, genomics, or molecular
            testing report.
        tumor_labels: Labels from a prior tumour-extraction pass. When given,
            the model is constrained to attribute each biomarker to one of
            them, so results can be grouped by tumour without fuzzy matching.

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
        "Extracting biomarkers from report (%d chars, %d known tumour label(s))",
        len(report_text),
        len(tumor_labels or []),
    )

    system_prompt = SYSTEM_PROMPT
    if tumor_labels:
        system_prompt += LABEL_VOCABULARY_PROMPT.format(
            labels="\n".join(f"  - {label}" for label in tumor_labels)
        )

    structured_llm = _get_structured_llm()

    try:
        result = structured_llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Extract biomarkers from:\n\n{report_text}"},
        ])
    except Exception as e:
        logger.error("Biomarker extraction failed: %s", e)
        raise

    if tumor_labels:
        for b in result.biomarkers:
            resolved = _resolve_label(b.tumor_label, tumor_labels)
            if b.tumor_label and resolved is None:
                logger.warning(
                    "Biomarker %s had unmatched tumour label %r — left unattributed",
                    b.gene,
                    b.tumor_label,
                )
            b.tumor_label = resolved

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