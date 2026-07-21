"""Tests for ChromaDB trial indexer and semantic search."""

from app.pipelines.therapy_matcher import load_therapy_database
from app.services.trial_indexer import (
    clear_index,
    get_trial_collection,
    index_trials,
    search_trials,
)


class TestTrialIndexing:
    def test_collection_is_created(self):
        collection = get_trial_collection()
        assert collection is not None
        assert collection.name == "clinical_trials"

    def test_index_and_search_synthetic_trials(self):
        """Index synthetic trials and verify semantic search works."""
        from app.services.clinical_trials_client import TrialSummary

        # Clear any previous test data
        clear_index()

        # Create synthetic trial summaries
        trials = [
            TrialSummary(
                nct_id="NCT-TEST-001",
                title="Osimertinib for EGFR Exon 19 Deletion in NSCLC",
                status="RECRUITING",
                phases=["PHASE3"],
                description="Phase 3 study of osimertinib in EGFR-mutant non-small cell lung cancer patients with exon 19 deletion.",
                eligibility="Inclusion: EGFR exon 19 deletion or L858R mutation. Exclusion: prior TKI therapy.",
                conditions=["Non-Small Cell Lung Cancer"],
                interventions=["Osimertinib"],
            ),
            TrialSummary(
                nct_id="NCT-TEST-002",
                title="Pembrolizumab for Melanoma Brain Metastases",
                status="RECRUITING",
                phases=["PHASE2"],
                description="Phase 2 trial of pembrolizumab in melanoma patients with brain metastases.",
                eligibility="Inclusion: metastatic melanoma with brain metastases. ECOG 0-1.",
                conditions=["Melanoma"],
                interventions=["Pembrolizumab"],
            ),
            TrialSummary(
                nct_id="NCT-TEST-003",
                title="Diet and Exercise in Breast Cancer Survivors",
                status="COMPLETED",
                phases=["NOT_APPLICABLE"],
                description="Lifestyle intervention study for breast cancer survivors.",
                eligibility="Inclusion: stage I-III breast cancer, completed treatment.",
                conditions=["Breast Cancer"],
                interventions=[],
            ),
        ]

        count = index_trials(trials)
        assert count == 3

        # Verify collection has 3 documents
        collection = get_trial_collection()
        assert collection.count() == 3

    def test_semantic_search_finds_relevant_trial(self):
        """Search for EGFR should return the EGFR trial as top result."""
        results = search_trials(
            query="targeted therapy for EGFR mutation lung cancer",
            n_results=2,
        )

        ids = results["ids"][0]
        assert len(ids) > 0, "Should return at least one result"
        assert "NCT-TEST-001" in ids, (
            f"EGFR trial should be top result, got: {ids}"
        )

    def test_semantic_search_different_domain(self):
        """Search for immunotherapy melanoma should find pembrolizumab trial."""
        results = search_trials(
            query="immunotherapy checkpoint inhibitor for melanoma",
            n_results=2,
        )

        ids = results["ids"][0]
        assert "NCT-TEST-002" in ids, (
            f"Melanoma trial should appear for immunotherapy query, got: {ids}"
        )

    def test_search_handles_empty_collection(self):
        """Search should return empty results when nothing is indexed."""
        # Clear and verify
        clear_index()
        collection = get_trial_collection()
        assert collection.count() == 0

        results = search_trials("lung cancer", n_results=5)
        assert results["ids"][0] == []

    def test_idempotent_indexing(self):
        """Indexing the same trial twice should not create duplicates."""
        from app.services.clinical_trials_client import TrialSummary

        clear_index()

        trial = TrialSummary(
            nct_id="NCT-TEST-DUP",
            title="Duplicate Test Trial",
            status="RECRUITING",
            phases=["PHASE1"],
            description="Testing idempotent indexing.",
            eligibility="All comers.",
            conditions=["Test"],
            interventions=[],
        )

        index_trials([trial])
        index_trials([trial])  # index again — should upsert, not duplicate

        collection = get_trial_collection()
        assert collection.count() == 1, (
            f"Expected 1 after upsert, got {collection.count()}"
        )
