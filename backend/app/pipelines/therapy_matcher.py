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

from app.models.biomarker import BiomarkerResult
from app.pipelines.reasoning_trace import create_trace

logger = logging.getLogger(__name__)

# Path to the curated therapy database
THERAPY_DATA_PATH = Path(__file__).parent.parent / "data" / "fda_therapies.json"


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

    for biomarker in biomarkers.biomarkers:
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

    logger.info(
        "Therapy matching: %d matches from %d biomarkers (%d unique drugs)",
        len(matches),
        len(biomarkers.biomarkers),
        len(unique_matches),
    )

    return unique_matches
