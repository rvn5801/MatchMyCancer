"""AI-powered trial eligibility summarization.

Takes dense clinical trial eligibility criteria and a patient profile,
then generates:
  1. Plain-language bullet-point summary of who qualifies
  2. Eligibility assessment: LIKELY, POSSIBLY, or UNLIKELY
  3. Brief reasoning for the assessment

This helps patients quickly understand if a trial is worth discussing
with their doctor, without reading 500 words of medical jargon.
"""

import logging
from typing import Dict

from langchain_openai import ChatOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

ELIGIBILITY_PROMPT = """\
You are a clinical trial navigator explaining eligibility criteria to a patient.

Given:
  1. Trial eligibility criteria (dense medical text)
  2. Patient profile (biomarkers, diagnosis, stage)

Do the following:

PART A — Plain-Language Summary:
  Summarize the key eligibility requirements in 3-5 bullet points
  using 8th-grade reading level. Focus on:
  - Cancer type and stage requirements
  - Biomarker/mutation requirements
  - Prior treatment restrictions
  - Other key factors (age, organ function, etc.)

PART B — Eligibility Assessment:
  Based on the patient profile, assess whether the patient is:
  - LIKELY ELIGIBLE: profile clearly matches criteria
  - POSSIBLY ELIGIBLE: profile partially matches, more info needed
  - UNLIKELY ELIGIBLE: profile conflicts with criteria

PART C — Reasoning:
  One sentence explaining the assessment.

Output format:
{
  "summary": ["bullet point 1", "bullet point 2", ...],
  "eligibility": "LIKELY ELIGIBLE" | "POSSIBLY ELIGIBLE" | "UNLIKELY ELIGIBLE",
  "reasoning": "One sentence explaining why"
}
"""

_summarizer_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _summarizer_llm
    if _summarizer_llm is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        _summarizer_llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.2,
            max_tokens=800,
        )
    return _summarizer_llm


def summarize_eligibility(
    eligibility_text: str,
    patient_profile: str,
) -> Dict[str, str]:
    """Summarize trial eligibility and assess patient fit.

    Args:
        eligibility_text: The trial's eligibility criteria text
            (from ClinicalTrials.gov).
        patient_profile: Concise patient summary including biomarkers,
            diagnosis, stage, and prior treatments.

    Returns:
        Dict with keys: summary, eligibility, reasoning.
    """
    if not eligibility_text or not eligibility_text.strip():
        raise ValueError("eligibility_text must not be empty")
    if not patient_profile or not patient_profile.strip():
        raise ValueError("patient_profile must not be empty")

    llm = _get_llm()

    response = llm.invoke([
        {"role": "system", "content": ELIGIBILITY_PROMPT},
        {
            "role": "user",
            "content": (
                f"Trial eligibility criteria:\n{eligibility_text[:3000]}\n\n"
                f"Patient profile:\n{patient_profile}"
            ),
        },
    ])

    # Parse the LLM's JSON response
    import json
    try:
        result = json.loads(response.content)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON — wrapping as raw text")
        result = {
            "summary": [response.content],
            "eligibility": "POSSIBLY ELIGIBLE",
            "reasoning": "Could not parse structured assessment from AI response.",
        }

    logger.info(
        "Eligibility assessment: %s", result.get("eligibility", "unknown")
    )
    return result
