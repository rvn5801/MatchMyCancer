"""Vector-based clinical trial indexing with ChromaDB.

Indexes clinical trials for semantic search. When keyword matching on
ClinicalTrials.gov misses relevant trials (e.g., a trial about "targeted
therapy for EGFR-mutant NSCLC" that doesn't mention "EGFR" in its title),
vector search can find it by semantic similarity.

Architecture:
  - ChromaDB stores trial embeddings locally (persistent, no server needed)
  - OpenAI text-embedding-3-small generates embeddings (1536-dim)
  - Each trial is indexed once, searched many times
  - Indexing is idempotent — re-indexing overwrites existing entries

Future: add batch indexing, incremental updates, and hybrid search
(keyword + vector).
"""

import logging
from typing import Dict, List, Optional

import chromadb
from chromadb.utils import embedding_functions

from app.core.config import settings
from app.services.clinical_trials_client import TrialSummary

logger = logging.getLogger(__name__)

COLLECTION_NAME = "clinical_trials"


def _get_embedding_function():
    """Get the OpenAI embedding function, or None if not configured."""
    if not settings.openai_api_key:
        logger.warning(
            "OPENAI_API_KEY not set — vector search will use default Chroma embeddings"
        )
        return embedding_functions.DefaultEmbeddingFunction()

    return embedding_functions.OpenAIEmbeddingFunction(
        api_key=settings.openai_api_key,
        model_name="text-embedding-3-small",
    )


def get_trial_collection():
    """Get or create the ChromaDB collection for clinical trials.

    Creates the collection on first call. Subsequent calls return
    the existing collection (persistent storage).

    Returns:
        ChromaDB Collection object.
    """
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    embedding_fn = _get_embedding_function()

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"description": "Clinical trial embeddings for semantic search"},
    )

    count = collection.count()
    logger.debug("ChromaDB collection '%s': %d documents", COLLECTION_NAME, count)
    return collection


def index_trials(trials: List[TrialSummary]) -> int:
    """Index clinical trials in ChromaDB for semantic search.

    For each trial, builds a searchable text blob from title, description,
    eligibility criteria, and conditions, then embeds and stores it.

    Re-indexing a trial (same NCT ID) overwrites the previous entry.

    Args:
        trials: List of TrialSummary objects to index.

    Returns:
        Number of trials indexed.
    """
    if not trials:
        return 0

    collection = get_trial_collection()
    indexed = 0

    for trial in trials:
        if not trial.nct_id:
            continue

        # Build rich searchable text
        text_parts = [trial.title]
        if trial.description:
            text_parts.append(trial.description)
        if trial.eligibility:
            text_parts.append(trial.eligibility)
        if trial.conditions:
            text_parts.append("Conditions: " + ", ".join(trial.conditions))
        if trial.interventions:
            text_parts.append("Interventions: " + ", ".join(trial.interventions))

        searchable_text = " | ".join(text_parts)[:8000]  # ChromaDB limit

        collection.upsert(
            documents=[searchable_text],
            metadatas=[{
                "nct_id": trial.nct_id,
                "title": trial.title[:500],
                "status": trial.status,
                "phases": ",".join(trial.phases),
                "verified_on": trial.status,  # We'll store status as proxy for now; real verified_on needs API call
            }],
            ids=[trial.nct_id],
        )
        indexed += 1

    logger.info("Indexed %d trials in ChromaDB", indexed)
    return indexed


def search_trials(
    query: str,
    n_results: int = 10,
) -> Dict:
    """Semantic search for clinical trials.

    Args:
        query: Natural language search query (e.g., "EGFR targeted
            therapy for stage IV lung adenocarcinoma").
        n_results: Number of results to return.

    Returns:
        ChromaDB query results dict with ids, documents, metadatas,
        and distances.
    """
    collection = get_trial_collection()

    if collection.count() == 0:
        logger.warning("ChromaDB collection is empty — no trials indexed yet")
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, collection.count()),
    )

    logger.info(
        "Vector search: '%s' → %d results",
        query[:80],
        len(results.get("ids", [[]])[0]),
    )

    return results


def clear_index() -> int:
    """Delete all indexed trials. Useful for re-indexing from scratch.

    Returns:
        Number of documents deleted.
    """
    collection = get_trial_collection()
    count = collection.count()
    if count > 0:
        # Delete by all IDs
        all_ids = collection.get()["ids"]
        if all_ids:
            collection.delete(ids=all_ids)
    logger.info("Cleared %d documents from ChromaDB", count)
    return count
