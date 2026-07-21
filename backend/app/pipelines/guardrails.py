"""Hallucination guardrails for AI-generated clinical content.

Prevents fabricated biomarkers, drugs, and trial IDs from reaching
patients. Each guardrail compares AI output against ground truth
(the source document or known databases).

Three layers of defense:
  1. Source verification — does the extracted biomarker appear in the report?
  2. Drug name validation — is the drug a real oncology drug?
  3. Confidence scoring — combines multiple signals into 0.0–1.0 score

All guardrails are deterministic (no LLM calls) — fast, free, and
auditable. They run after extraction but before the explanation is
shown to the patient.
"""

import logging
import re
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# ── Known drug suffixes for oncology therapies ──────────────────────────────

# Common oncology drug name patterns (USAN stems).
# These regex patterns match the suffix conventions used in drug naming:
#   -mab: monoclonal antibodies (e.g., trastuzumab)
#   -nib: tyrosine kinase inhibitors (e.g., osimertinib)
#   -mide: immunomodulators (e.g., lenalidomide)
#   -parib: PARP inhibitors (e.g., olaparib)
#   -ciclib: CDK inhibitors (e.g., palbociclib)
#   -lisib: PI3K inhibitors (e.g., alpelisib)
#   -sertib: AKT inhibitors (e.g., ipatasertib)
#   -stat: statins and related (e.g., atorvastatin)
#   -ant: antiandrogens (e.g., enzalutamide — not exact match but close)
#   -icin: anthracyclines (e.g., doxorubicin)
#   -tin: platinum agents (e.g., cisplatin)

_DRUG_SUFFIX_PATTERN = re.compile(
    r'\b([A-Z][a-z]+(?:mab|nib|mide|parib|ciclib|lisib|sertib|'
    r'stat|ant|icin|tin|lin|cept|ximab|zumab|rumab|omab))'
    r'\b',
    re.IGNORECASE,
)


# ── Source verification ─────────────────────────────────────────────────────


def validate_biomarker_against_source(
    biomarkers: List[Dict[str, Any]],
    source_text: str,
) -> List[Dict[str, Any]]:
    """Check whether each extracted biomarker appears in the source text.

    Uses case-insensitive substring matching. A biomarker that doesn't
    appear in the source text at all is flagged as a possible hallucination.

    Args:
        biomarkers: List of biomarker dicts (must have 'gene' key).
        source_text: The original report text the biomarkers were
            extracted from.

    Returns:
        The same list with two added fields per biomarker:
          - source_verified: bool — True if gene name found in source
          - warning: str or None — human-readable warning if not verified

    Example:
        >>> validate_biomarker_against_source(
        ...     [{"gene": "EGFR"}],
        ...     "Patient has EGFR mutation."
        ... )
        [{"gene": "EGFR", "source_verified": True, "warning": None}]
    """
    if not source_text or not source_text.strip():
        logger.warning("Source text is empty — cannot verify biomarkers")
        return [
            {**b, "source_verified": False, "warning": "No source text to verify against"}
            for b in biomarkers
        ]

    source_upper = source_text.upper()
    validated = []

    for b in biomarkers:
        gene = str(b.get("gene", "")).strip()
        if not gene:
            validated.append({**b, "source_verified": False, "warning": "No gene name provided"})
            continue

        present = gene.upper() in source_upper

        if present:
            validated.append({**b, "source_verified": True, "warning": None})
            logger.debug("Verified: %s found in source text", gene)
        else:
            validated.append({
                **b,
                "source_verified": False,
                "warning": (
                    f"'{gene}' not found in source text — "
                    f"this may be a hallucination"
                ),
            })
            logger.warning("Possible hallucination: %s not in source text", gene)

    verified_count = sum(1 for v in validated if v["source_verified"])
    logger.info(
        "Source verification: %d/%d biomarkers verified",
        verified_count,
        len(validated),
    )

    return validated


# ── Drug name validation ────────────────────────────────────────────────────


def check_for_hallucinated_drugs(
    recommendation_text: str,
    known_drugs: Optional[set[str]] = None,
) -> List[str]:
    """Flag drug names in recommendation text that are not in known_drugs.

    Uses regex to detect drug-like words (based on USAN naming conventions)
    and compares against a known set of oncology drugs.

    Args:
        recommendation_text: The AI-generated recommendation.
        known_drugs: Set of known/verified oncology drug names (lowercase).
            If None, only pattern-matches without filtering.

    Returns:
        List of drug-like words NOT in known_drugs (possible hallucinations).
        Empty list if all detected drugs are known.
    """
    if not recommendation_text or not recommendation_text.strip():
        return []

    mentioned = set(
        match.group(0).lower()
        for match in _DRUG_SUFFIX_PATTERN.finditer(recommendation_text)
    )

    if not mentioned:
        logger.debug("No drug-like words detected in text")
        return []

    if known_drugs is None:
        logger.debug("No known_drugs set — returning all detected drug names")
        return sorted(mentioned)

    unknown = mentioned - {d.lower() for d in known_drugs}

    if unknown:
        logger.warning(
            "Possible hallucinated drugs: %s (detected %d total)",
            ", ".join(sorted(unknown)),
            len(mentioned),
        )

    return sorted(unknown)


# ── Confidence scoring ──────────────────────────────────────────────────────


def calculate_confidence(
    source_verification_rate: float,
    has_disclaimer: bool = False,
    source_count: int = 0,
) -> float:
    """Calculate overall confidence score from multiple signals.

    Weights:
      - Source verification rate: 60% — the biggest factor
      - Disclaimer presence: 15% — shows the AI knows its limits
      - Having 2+ sources: 10% — multiple sources = more reliable
      - Source count bonus: up to 15% (5% per source, max 3 sources)

    Args:
        source_verification_rate: Fraction of biomarkers verified in
            source text (0.0–1.0).
        has_disclaimer: Whether the output includes a medical disclaimer.
        source_count: Number of external sources cited.

    Returns:
        Confidence score clamped to 0.0–1.0.
    """
    score = 0.0

    # Source verification is the biggest signal
    score += source_verification_rate * 0.6

    # Disclaimer shows self-awareness of limitations
    if has_disclaimer:
        score += 0.15

    # Multiple sources increase confidence
    if source_count >= 2:
        score += 0.1

    # Bonus per source (up to 3)
    score += min(source_count * 0.05, 0.15)

    return round(min(score, 1.0), 2)
