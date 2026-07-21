"""Trial refresh job — re-validates trial status from ClinicalTrials.gov and updates ChromaDB.

Run as a cron job (daily/weekly) to keep the trial index fresh.
Stale trials (>30 days since verified_on) are down-ranked in matching.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from app.services.clinical_trials_client import ClinicalTrialsClient
from app.services.trial_indexer import get_trial_collection

logger = logging.getLogger(__name__)

STALE_THRESHOLD_DAYS = 30


async def refresh_trial_status(nct_id: str, client: ClinicalTrialsClient) -> Optional[dict]:
    """Fetch fresh status for a single trial from ClinicalTrials.gov."""
    try:
        studies = await client.search_studies(
            condition="",  # Empty condition with NCT ID filter
            intervention=nct_id,
            page_size=1,
        )
        if studies:
            study = studies[0]
            return {
                "nct_id": study.nct_id,
                "status": study.status,
                "verified_on": date.today().isoformat(),
            }
    except Exception as e:
        logger.warning("Failed to refresh trial %s: %s", nct_id, e)
    return None


async def refresh_all_trials(days_threshold: int = STALE_THRESHOLD_DAYS) -> dict:
    """Re-fetch status for all indexed trials, update ChromaDB with verified_on.

    Returns summary dict with counts.
    """
    collection = get_trial_collection()
    all_data = collection.get(include=["metadatas"])
    nct_ids = [meta.get("nct_id") for meta in all_data.get("metadatas", []) if meta.get("nct_id")]

    logger.info("Starting trial refresh for %d trials", len(nct_ids))

    async with ClinicalTrialsClient() as client:
        refreshed = 0
        stale = 0
        failed = 0

        for i, nct_id in enumerate(nct_ids):
            result = await refresh_trial_status(nct_id, client)
            if result:
                # Update ChromaDB with fresh verified_on
                meta = all_data["metadatas"][i] if i < len(all_data["metadatas"]) else {}
                collection.update(
                    ids=[nct_id],
                    metadatas=[{
                        "nct_id": result["nct_id"],
                        "title": meta.get("title", ""),
                        "status": result["status"],
                        "phases": meta.get("phases", ""),
                        "verified_on": result["verified_on"],
                    }],
                )
                refreshed += 1
                # Check if stale
                verified_date = datetime.fromisoformat(result["verified_on"]).date()
                if (date.today() - verified_date).days > days_threshold:
                    stale += 1
            else:
                failed += 1

            # Be nice to the API
            await asyncio.sleep(0.1)

    logger.info(
        "Trial refresh complete: %d refreshed, %d stale, %d failed",
        refreshed, stale, failed
    )
    return {"refreshed": refreshed, "stale": stale, "failed": failed}


async def downrank_stale_trials(days_threshold: int = STALE_THRESHOLD_DAYS) -> int:
    """Mark stale trials in ChromaDB metadata for down-ranking.

    Returns count of trials marked stale.
    """
    collection = get_trial_collection()
    all_data = collection.get(include=["metadatas"])
    metadatas = all_data.get("metadatas", [])
    ids = all_data.get("ids", [])

    stale_count = 0
    for i, meta in enumerate(metadatas):
        verified_str = meta.get("verified_on")
        if verified_str:
            try:
                verified_date = datetime.fromisoformat(verified_str).date()
                is_stale = (date.today() - verified_date).days > days_threshold
                if is_stale and not meta.get("is_stale"):
                    collection.update(
                        ids=[ids[i]],
                        metadatas=[{**meta, "is_stale": True, "stale_since": date.today().isoformat()}],
                    )
                    stale_count += 1
            except ValueError:
                pass  # Invalid date format, skip

    logger.info("Marked %d trials as stale (>%d days)", stale_count, days_threshold)
    return stale_count


if __name__ == "__main__":
    # CLI entry point for cron
    logging.basicConfig(level=logging.INFO)
    asyncio.run(refresh_all_trials())
    asyncio.run(downrank_stale_trials())