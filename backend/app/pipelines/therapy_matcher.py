"""FDA-approved therapy matching engine.

Matches patient biomarkers to FDA-approved targeted therapies using
a curated oncology therapy database. The database maps biomarkers →
drugs based on OncoKB Level 1 evidence (FDA-recognized).

Future: will be augmented with live OncoKB API queries.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from app.models.biomarker import Biomarker, BiomarkerCall, BiomarkerResult
from app.pipelines.reasoning_trace import create_trace

logger = logging.getLogger(__name__)

# Path to the curated therapy database
THERAPY_DATA_PATH = Path(__file__).parent.parent / "data" / "fda_therapies.json"

# Free-text phrasings that mean the target is ABSENT. Consulted only when the
# structured `result` call is UNKNOWN, so a missing call cannot defeat the guard.
#
# "loss" and "deletion" are deliberately NOT here: CDKN2A loss and BRCA
# deletions are the actionable finding, not its absence.
_NEGATIVE_PATTERNS = (
    r"\bnegative\b",
    r"\bnot amplified\b",
    r"\bnon-?amplified\b",
    r"\bno amplification\b",
    r"\bnot detected\b",
    r"\bundetected\b",
    r"\bnone detected\b",
    r"\bwild[\s-]?type\b",
    r"\babsent\b",
)

_EQUIVOCAL_PATTERNS = (
    r"\bequivocal\b",
    r"\bindeterminate\b",
    r"\bborderline\b",
    r"\bpending\b",
    r"\bquantity not sufficient\b",
    r"\bQNS\b",
)

# A variant can be DETECTED and still not be a treatment target. These override
# a positive call: "EGFR p.L861X, variant of unknown significance" is a finding,
# not an indication for osimertinib.
_NON_ACTIONABLE_SIGNIFICANCE = (
    r"\bvariants? of (unknown|uncertain) significance\b",
    r"\b(unknown|uncertain) significance\b",
    r"\bVUS\b",
    r"\blikely benign\b",
    r"\bbenign\b",
)


def is_actionable(biomarker: Biomarker) -> bool:
    """True only when the report says the target is PRESENT and treatable.

    A gene symbol records that a marker was tested, not what the answer was.
    Matching on the symbol alone recommends anti-HER2 therapy to a
    HER2-negative patient — measured on TCGA-BH-A18H, a bilateral breast case
    where ERBB2 'negative' matched trastuzumab, pertuzumab, T-DM1 and T-DXd.

    Two things block a match, and both default to "do not treat":
      - the target was not established (negative, equivocal, not tested)
      - the target was found but is not a treatment target (VUS, benign)

    ponytail: the UNKNOWN fallback is regex over free text, so a compound
    string ("exon 19 deletion, T790M negative") reads as negative and drops a
    real match. Set Biomarker.result explicitly and the heuristic never runs.
    """
    # Significance overrides the call: detected-but-uninterpretable is not a
    # treatment target, however confidently it was detected.
    significance = (biomarker.significance or "").lower()
    if any(
        re.search(p, significance, re.IGNORECASE)
        for p in _NON_ACTIONABLE_SIGNIFICANCE
    ):
        return False

    if biomarker.result is BiomarkerCall.POSITIVE:
        return True
    if biomarker.result in (
        BiomarkerCall.NEGATIVE,
        BiomarkerCall.EQUIVOCAL,
        BiomarkerCall.NOT_TESTED,
    ):
        return False

    haystack = " ".join(
        part
        for part in (
            biomarker.alteration,
            biomarker.significance,
            biomarker.alteration_type,
        )
        if part
    )

    # IGNORECASE rather than lower(): acronym patterns like \bQNS\b and \bVUS\b
    # are written uppercase and would never match a lowercased haystack.
    return not any(
        re.search(p, haystack, re.IGNORECASE)
        for p in _NEGATIVE_PATTERNS + _EQUIVOCAL_PATTERNS
    )


def load_therapy_database() -> List[Dict[str, Any]]:
    """Load the FDA-approved therapy database from disk.

    Returns:
        List of therapy dicts with keys: drug, biomarker, alteration,
        cancer_type, fda_approval_year, source.
    """
    if not THERAPY_DATA_PATH.exists():
        logger.warning(
            "Therapy database not found at %s — returning empty list",
            THERAPY_DATA_PATH,
        )
        return []

    with open(THERAPY_DATA_PATH) as f:
        therapies = json.load(f)

    logger.info("Loaded %d therapies from database", len(therapies))
    return therapies


def match_therapies(biomarkers: BiomarkerResult) -> List[Dict[str, Any]]:
    """Match patient biomarkers to FDA-approved therapies.

    Performs case-insensitive gene name matching against the therapy
    database. Returns therapies where the patient's biomarker gene
    matches the therapy's target biomarker.

    Args:
        biomarkers: Extracted biomarker results.

    Returns:
        List of matched therapy dicts, each with added fields:
          - matched_biomarker: the patient's gene that triggered the match
          - patient_alteration: the specific alteration found
          - match_quality: "exact" or "partial"
    """
    therapies = load_therapy_database()
    if not therapies:
        return []

    matches = []
    skipped: List[str] = []

    for biomarker in biomarkers.biomarkers:
        # The gene says what was tested; the result says what was found.
        # Matching without this check recommends drugs against absent targets.
        if not is_actionable(biomarker):
            skipped.append(
                f"{biomarker.gene} (result={biomarker.result.value}, "
                f"alteration={biomarker.alteration!r})"
            )
            continue

        gene_upper = biomarker.gene.upper()

        for therapy in therapies:
            therapy_biomarker = therapy.get("biomarker", "").upper()

            # Exact gene match, or gene as a whole word in the therapy's
            # biomarker field (word-boundary avoids e.g. "KIT" matching "KITLG").
            if gene_upper == therapy_biomarker:
                match_quality = "exact"
            elif re.search(rf"\b{re.escape(gene_upper)}\b", therapy_biomarker):
                match_quality = "partial"
            else:
                continue

            # Deterministic audit trail: how this drug was reached (no LLM).
            alt = biomarker.alteration or "alteration"
            trace = create_trace(
                recommendation_text=(
                    f"{therapy['drug']} targets {therapy.get('biomarker', biomarker.gene)} "
                    f"({therapy.get('alteration', 'alteration')})"
                ),
                rec_type="therapy",
                steps=[
                    {"description": f"Detected {biomarker.gene} {alt} in the report"},
                    {"description": (
                        f"Matched {biomarker.gene} to FDA-approved {therapy['drug']} "
                        f"via {therapy.get('source', 'OncoKB')} evidence "
                        f"({match_quality} gene match)"
                    )},
                ],
                sources=[{
                    "source_name": therapy.get("source", "OncoKB"),
                    "relevance": (
                        f"FDA approval {therapy.get('fda_approval_year', 'n/a')} "
                        f"for {therapy.get('cancer_type', 'cancer')}"
                    ),
                }],
            )

            matches.append({
                **therapy,
                "matched_biomarker": biomarker.gene,
                "patient_alteration": biomarker.alteration,
                "match_quality": match_quality,
                "trace": trace.model_dump(mode="json"),
            })

    # Deduplicate by drug name (same drug may match multiple biomarkers)
    seen_drugs: set[str] = set()
    unique_matches = []
    for m in matches:
        drug_key = m["drug"].lower()
        if drug_key not in seen_drugs:
            seen_drugs.add(drug_key)
            unique_matches.append(m)

    if skipped:
        logger.info(
            "Therapy matching skipped %d non-positive biomarker(s): %s",
            len(skipped),
            "; ".join(skipped),
        )

    logger.info(
        "Therapy matching: %d matches from %d biomarkers (%d unique drugs)",
        len(matches),
        len(biomarkers.biomarkers),
        len(unique_matches),
    )

    return unique_matches
