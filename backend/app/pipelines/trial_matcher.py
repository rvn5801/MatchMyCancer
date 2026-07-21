"""Clinical trial matching orchestrator.

Given biomarker + diagnosis data, searches ClinicalTrials.gov for
matching trials and returns deduplicated, formatted results with
freshness metadata (verified_on, is_stale).
"""

import logging
from datetime import date
from typing import Dict, List

from app.core.config import settings
from app.models.biomarker import BiomarkerResult
from app.pipelines.eligibility_summarizer import summarize_eligibility
from app.services.clinical_trials_client import ClinicalTrialsClient, TrialSummary
from app.services.trial_indexer import get_trial_collection

logger = logging.getLogger(__name__)

STALE_THRESHOLD_DAYS = 30
ELIGIBILITY_TOP_N = 5  # only the top matches get an AI eligibility summary (cost)


def _build_patient_profile(biomarkers: BiomarkerResult, condition: str) -> str:
    """Concise patient profile string for eligibility assessment."""
    parts = [f"Diagnosis: {condition}"]
    if biomarkers.biomarkers:
        genes = ", ".join(
            f"{b.gene} {b.alteration or ''}".strip() for b in biomarkers.biomarkers
        )
        parts.append(f"Biomarkers: {genes}")
    if biomarkers.msi_status:
        parts.append(f"MSI: {biomarkers.msi_status}")
    if biomarkers.pd_l1_score:
        parts.append(f"PD-L1: {biomarkers.pd_l1_score}")
    return "; ".join(parts)


def _enrich_eligibility(trials: List[TrialSummary], patient_profile: str) -> None:
    """Attach AI eligibility summary to the top-N trials, in place.

    Gated on OPENAI_API_KEY; per-trial try/except so one failure never
    breaks analysis. Skips trials with no eligibility text.
    """
    if not settings.openai_api_key:
        return
    for trial in trials[:ELIGIBILITY_TOP_N]:
        if not trial.eligibility or not trial.eligibility.strip():
            continue
        try:
            result = summarize_eligibility(trial.eligibility, patient_profile)
            summary = result.get("summary")
            trial.eligibility_summary = summary if isinstance(summary, list) else [str(summary)]
            trial.eligibility_assessment = result.get("eligibility")
            trial.eligibility_reasoning = result.get("reasoning")
        except Exception as e:
            logger.warning("Eligibility summary failed for %s: %s", trial.nct_id, e)


def _tier_from_freshness(verified_on: str | None) -> str:
    """Convert verified_on date to freshness tier."""
    if not verified_on:
        return "MEDIUM"  # no data = assume medium
    try:
        verified_date = date.fromisoformat(verified_on)
        days_old = (date.today() - verified_date).days
        if days_old <= STALE_THRESHOLD_DAYS:
            return "HIGHEST"
        else:
            return "LOW"
    except ValueError:
        return "MEDIUM"


async def _enrich_trial_freshness(trials: List[TrialSummary]) -> List[TrialSummary]:
    """Add verified_on and freshness tier from ChromaDB index."""
    collection = get_trial_collection()
    nct_ids = [t.nct_id for t in trials]
    
    # Batch fetch metadata from ChromaDB
    results = collection.get(ids=nct_ids, include=["metadatas"])
    meta_by_nct = {meta.get("nct_id"): meta for meta in results.get("metadatas", []) if meta}
    
    for trial in trials:
        meta = meta_by_nct.get(trial.nct_id)
        if meta:
            trial.verified_on = meta.get("verified_on")
            trial.tier = _tier_from_freshness(trial.verified_on)
            trial.is_stale = meta.get("is_stale", False)
        else:
            trial.tier = "MEDIUM"
    
    # Sort: HIGHEST first, then by relevance (biomarker matches already first)
    trials.sort(key=lambda t: (
        0 if getattr(t, 'tier', 'MEDIUM') == 'HIGHEST' else
        1 if getattr(t, 'tier', 'MEDIUM') == 'MEDIUM' else 2
    ))
    return trials


async def find_matching_trials(
    biomarkers: BiomarkerResult,
    condition: str,
    max_trials: int = 20,
) -> List[TrialSummary]:
    """Search for clinical trials matching patient biomarkers and diagnosis.

    Performs one search per biomarker gene + one broad condition search,
    then deduplicates by NCT ID.

    Args:
        biomarkers: Extracted biomarker results from the clinical report.
        condition: Cancer type (e.g., "lung cancer", "breast cancer").
        max_trials: Maximum number of unique trials to return.

    Returns:
        Deduplicated list of TrialSummary objects, sorted by relevance
        (biomarker-specific matches first).
    """
    if not condition:
        condition = "cancer"

    async with ClinicalTrialsClient() as client:
        seen_ids: set[str] = set()
        all_trials: List[TrialSummary] = []

        # Strategy 1: biomarker-specific searches (most relevant)
        for biomarker in biomarkers.biomarkers:
            gene = biomarker.gene
            alteration = biomarker.alteration or ""

            query = f"{gene} {alteration}" if alteration else gene
            logger.info("Searching trials for biomarker: %s", query)

            trials = await client.search_by_biomarker(
                biomarker=query,
                condition=condition,
                page_size=10,
            )

            for trial in trials:
                if trial.nct_id not in seen_ids:
                    seen_ids.add(trial.nct_id)
                    all_trials.append(trial)

            if len(all_trials) >= max_trials:
                break

        # Strategy 2: broad condition search (fallback for more options)
        if len(all_trials) < max_trials:
            logger.info(
                "Broad search: %s (have %d, need %d)",
                condition,
                len(all_trials),
                max_trials,
            )
            broad_trials = await client.search_studies(
                condition=condition,
                page_size=max_trials,
            )
            for trial in broad_trials:
                if trial.nct_id not in seen_ids:
                    seen_ids.add(trial.nct_id)
                    all_trials.append(trial)
                if len(all_trials) >= max_trials:
                    break

    result = all_trials[:max_trials]

    # AI eligibility summary for the top matches (best-effort, gated on API key).
    _enrich_eligibility(result, _build_patient_profile(biomarkers, condition))

    logger.info(
        "Trial matching complete: %d unique trials for %s",
        len(result),
        condition,
    )
    return result
