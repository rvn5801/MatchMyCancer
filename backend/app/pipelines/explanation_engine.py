"""Patient-friendly explanation engine for biomarker results.

Generates plain-language explanations of biomarkers, diagnoses, and
their treatment implications. Uses free-text LLM output (not structured)
because the goal is readable prose for patients, not typed data.

Key design:
  - Temperature 0.3 — warmer than extraction (0.0) for natural language,
    but still conservative for medical content
  - 8th-grade reading level target — complex terms get broken down
  - Mandatory disclaimer on every output
  - Separate functions for per-biomarker explanations and overall summary
"""

import logging
import re

from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.models.biomarker import BiomarkerResult

logger = logging.getLogger(__name__)

# ── Prompts ─────────────────────────────────────────────────────────────────

BIOMARKER_EXPLANATION_PROMPT = """\
You are a compassionate medical educator explaining oncology results to patients.

Follow these rules strictly:
1. Use plain language at an 8th-grade reading level.
2. Explain what the biomarker/gene IS, what it does normally in the body,
   and what the alteration means for the patient's cancer.
3. Explain why this finding matters for treatment decisions — mention
   therapy CATEGORIES affected (e.g., "targeted therapy", "immunotherapy",
   "chemotherapy") without naming specific drugs or dosages.
4. Each explanation should be 3-5 sentences, clear and direct.
5. Do NOT use markdown formatting (no **bold**, no _italics_).
   Plain text only.
6. DO NOT fabricate information — only explain what is provided.
7. Include this exact disclaimer at the end of each explanation:
   "This is informational only. Discuss all treatment decisions with your oncologist."
"""

CLINICAL_SUMMARY_PROMPT = """\
You are a compassionate oncology nurse summarizing test results for a patient.

You are given the structured clinical extraction from the patient's oncology
report, including biomarkers found and diagnosis details.

Write a clear, compassionate summary following these rules:
1. Use plain language (8th-grade reading level).
2. Start with a brief, empathetic sentence acknowledging the patient.
3. List key findings as bullet points with simple explanations.
4. For each finding with known treatment relevance, mention the therapy
   category (targeted therapy, immunotherapy, chemotherapy, clinical trial)
   but do NOT recommend specific drugs.
5. Do NOT use markdown formatting (no **, no __, no ## headings).
   Use plain text only with simple dashes for bullet points.
6. End with this exact disclaimer:
   "This summary is for educational purposes only. Please discuss all findings and treatment options with your oncology team before making any decisions."
"""


# ── LLM client ──────────────────────────────────────────────────────────────

_explanation_llm: ChatOpenAI | None = None


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting characters from LLM output."""
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # Italic: *text* or _text_
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    return text


def _get_llm() -> ChatOpenAI:
    global _explanation_llm
    if _explanation_llm is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        _explanation_llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.3,  # warmer for natural language, still conservative
            max_tokens=1000,
        )
    return _explanation_llm


# ── Public API ──────────────────────────────────────────────────────────────


def explain_biomarkers(biomarkers: BiomarkerResult) -> list[dict]:
    """Generate plain-language explanations for each biomarker.

    Args:
        biomarkers: Extracted biomarker results from a clinical report.

    Returns:
        List of dicts with gene, alteration, explanation, and the full
        biomarker data for traceability.
    """
    if not biomarkers.biomarkers:
        logger.info("No biomarkers to explain — returning empty list")
        return []

    llm = _get_llm()
    explanations = []

    for biomarker in biomarkers.biomarkers:
        gene = biomarker.gene
        alteration = biomarker.alteration or "alteration"
        alteration_type = biomarker.alteration_type or "unknown type"

        logger.info("Explaining biomarker: %s %s", gene, alteration)

        user_message = (
            f"Explain in plain language for a patient: "
            f"Their tumor has a {alteration_type} in the {gene} gene. "
            f"Specific finding: {gene} {alteration}."
        )

        response = llm.invoke([
            {"role": "system", "content": BIOMARKER_EXPLANATION_PROMPT},
            {"role": "user", "content": user_message},
        ])

        explanations.append({
            "gene": gene,
            "alteration": alteration,
            "explanation": _strip_markdown(response.content),
            "biomarker": biomarker.model_dump(),
        })

    logger.info("Generated %d biomarker explanations", len(explanations))
    return explanations


def generate_clinical_summary(extraction_result: dict) -> str:
    """Generate a patient-friendly summary of the full clinical extraction.

    Args:
        extraction_result: The complete ClinicalExtraction as a dict
            (from extract_clinical_data or the extract API).

    Returns:
        Plain-language summary string suitable for display to patients.
    """
    llm = _get_llm()

    # Build a concise representation for the LLM
    biomarkers = extraction_result.get("biomarkers", {})
    diagnosis = extraction_result.get("diagnosis", {}) or {}

    context_parts = []

    bm_list = biomarkers.get("biomarkers", [])
    if bm_list:
        bm_summary = ", ".join(
            f"{b['gene']} {b.get('alteration', 'altered')}" for b in bm_list
        )
        context_parts.append(f"Biomarkers found: {bm_summary}")

    if biomarkers.get("msi_status"):
        context_parts.append(f"MSI Status: {biomarkers['msi_status']}")
    if biomarkers.get("tmb"):
        context_parts.append(f"TMB: {biomarkers['tmb']} mut/Mb")
    if biomarkers.get("pd_l1_score"):
        context_parts.append(f"PD-L1: {biomarkers['pd_l1_score']}")

    if diagnosis:
        diag_parts = []
        if diagnosis.get("primary_site"):
            diag_parts.append(diagnosis["primary_site"])
        if diagnosis.get("histology"):
            diag_parts.append(diagnosis["histology"])
        if diagnosis.get("stage"):
            diag_parts.append(diagnosis["stage"])
        if diag_parts:
            context_parts.append(f"Diagnosis: {' — '.join(diag_parts)}")

    context = "\n".join(context_parts)
    logger.info("Generating clinical summary from %d findings", len(context_parts))

    response = llm.invoke([
        {"role": "system", "content": CLINICAL_SUMMARY_PROMPT},
        {"role": "user", "content": context},
    ])

    return _strip_markdown(response.content)
