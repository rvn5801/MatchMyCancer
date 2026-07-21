"""Tests for clinical trial matcher orchestrator."""

import pytest

from app.models.biomarker import Biomarker, BiomarkerResult
from app.pipelines.trial_matcher import find_matching_trials


@pytest.mark.network
@pytest.mark.asyncio
class TestTrialMatcher:
    async def test_finds_trials_for_egfr_lung(self):
        biomarkers = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="EGFR",
                    alteration="exon 19 deletion",
                    alteration_type="mutation",
                    raw_text="EGFR exon 19 deletion",
                ),
            ],
            msi_status="MSS",
        )

        trials = await find_matching_trials(
            biomarkers=biomarkers,
            condition="lung cancer",
            max_trials=10,
        )

        assert len(trials) > 0, "Should find at least one trial"
        for trial in trials:
            assert trial.nct_id, "Every trial must have an NCT ID"
            assert trial.title, "Every trial must have a title"

    async def test_finds_trials_for_braf_melanoma(self):
        biomarkers = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="BRAF",
                    alteration="V600E",
                    alteration_type="mutation",
                    raw_text="BRAF V600E",
                ),
            ],
        )

        trials = await find_matching_trials(
            biomarkers=biomarkers,
            condition="melanoma",
            max_trials=10,
        )

        assert len(trials) > 0, "Should find melanoma trials"

    async def test_respects_max_trials(self):
        biomarkers = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="EGFR",
                    alteration="L858R",
                    alteration_type="mutation",
                    raw_text="EGFR L858R",
                ),
            ],
        )

        trials = await find_matching_trials(
            biomarkers=biomarkers,
            condition="lung cancer",
            max_trials=5,
        )

        assert len(trials) <= 5

    async def test_deduplicates_trials(self):
        """Two biomarkers shouldn't return duplicate trial NCT IDs."""
        biomarkers = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="EGFR",
                    alteration="exon 19 deletion",
                    alteration_type="mutation",
                    raw_text="ex19del",
                ),
                Biomarker(
                    gene="ALK",
                    alteration="rearrangement",
                    alteration_type="fusion",
                    raw_text="ALK fusion",
                ),
            ],
        )

        trials = await find_matching_trials(
            biomarkers=biomarkers,
            condition="lung cancer",
            max_trials=15,
        )

        nct_ids = [t.nct_id for t in trials]
        assert len(nct_ids) == len(set(nct_ids)), "Trial IDs must be unique"

    async def test_empty_biomarkers_still_searches(self):
        """Even with no biomarkers, should do a broad condition search."""
        biomarkers = BiomarkerResult(biomarkers=[])

        trials = await find_matching_trials(
            biomarkers=biomarkers,
            condition="breast cancer",
            max_trials=5,
        )

        assert len(trials) > 0, "Should find breast cancer trials via broad search"
