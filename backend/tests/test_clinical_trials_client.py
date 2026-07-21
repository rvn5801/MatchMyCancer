"""Tests for ClinicalTrials.gov API client.

Tests the real API (ClinicalTrials.gov v2 is public, no auth needed).
Uses pytest.mark.asyncio for async test support.
"""

import pytest

from app.services.clinical_trials_client import ClinicalTrialsClient, TrialSummary


class TestTrialSummaryParsing:
    """Static parsing tests — no network needed."""

    def test_parses_full_trial_response(self):
        """Verify TrialSummary.from_api_response handles a real response shape."""
        trial = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT01234567",
                    "briefTitle": "Osimertinib for EGFR-Mutant NSCLC",
                },
                "statusModule": {
                    "overallStatus": "RECRUITING",
                },
                "designModule": {
                    "phases": ["PHASE3"],
                },
                "descriptionModule": {
                    "briefSummary": "This study evaluates osimertinib in patients with EGFR mutations.",
                },
                "eligibilityModule": {
                    "eligibilityCriteria": "Inclusion: EGFR T790M mutation. Exclusion: prior osimertinib.",
                },
                "conditionsModule": {
                    "conditions": ["Non-Small Cell Lung Cancer"],
                },
                "armsInterventionsModule": {
                    "interventions": [
                        {"type": "DRUG", "name": "Osimertinib"},
                        {"type": "DRUG", "name": "Placebo"},
                    ],
                },
                "contactsLocationsModule": {
                    "locations": [
                        {
                            "facility": "MD Anderson Cancer Center",
                            "city": "Houston",
                            "state": "Texas",
                            "country": "United States",
                        },
                    ],
                },
            },
        }

        result = TrialSummary.from_api_response(trial)

        assert result.nct_id == "NCT01234567"
        assert "Osimertinib" in result.title
        assert result.status == "RECRUITING"
        assert "PHASE3" in result.phases
        assert len(result.description) > 10
        assert len(result.eligibility) > 10
        assert len(result.conditions) == 1
        assert "Non-Small Cell Lung Cancer" in result.conditions
        assert len(result.interventions) == 2
        assert "Osimertinib" in result.interventions
        assert len(result.locations) == 1
        assert result.locations[0]["city"] == "Houston"

    def test_parses_minimal_trial_response(self):
        """Handle trials with missing optional fields."""
        trial = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT00000000",
                    "briefTitle": "Minimal Trial",
                },
                "statusModule": {"overallStatus": "COMPLETED"},
                "designModule": {},
                "descriptionModule": {},
                "eligibilityModule": {},
                "conditionsModule": {},
                "armsInterventionsModule": {},
                "contactsLocationsModule": {},
            },
        }

        result = TrialSummary.from_api_response(trial)

        assert result.nct_id == "NCT00000000"
        assert result.status == "COMPLETED"
        assert result.phases == []
        assert result.description == ""
        assert result.conditions == []
        assert result.interventions == []
        assert result.locations == []

    def test_handles_missing_sections(self):
        """Handle malformed responses gracefully."""
        trial = {"protocolSection": {}}

        result = TrialSummary.from_api_response(trial)

        assert result.nct_id == ""
        assert result.title == ""
        assert result.status == ""


@pytest.mark.network
@pytest.mark.asyncio
class TestClinicalTrialsClient:
    """Integration tests — calls the real ClinicalTrials.gov API."""

    async def test_search_lung_cancer_returns_results(self):
        async with ClinicalTrialsClient() as client:
            results = await client.search_studies(
                condition="lung cancer",
                page_size=5,
            )

        assert len(results) > 0, "Should find at least one lung cancer trial"
        for trial in results:
            assert isinstance(trial, TrialSummary)
            assert trial.nct_id, "Every trial should have an NCT ID"
            assert trial.title, "Every trial should have a title"
            assert trial.status, "Every trial should have a status"

    async def test_search_by_biomarker_returns_results(self):
        async with ClinicalTrialsClient() as client:
            results = await client.search_by_biomarker(
                biomarker="EGFR",
                condition="lung cancer",
                page_size=5,
            )

        assert len(results) > 0, "Should find EGFR + lung cancer trials"
        # Not all results will mention EGFR in the title, but they should
        # be related to lung cancer
        for trial in results:
            assert isinstance(trial, TrialSummary)
            assert trial.nct_id

    async def test_search_respects_page_size(self):
        async with ClinicalTrialsClient() as client:
            results = await client.search_studies(
                condition="breast cancer",
                page_size=3,
            )

        assert len(results) <= 3

    async def test_get_study_returns_details(self):
        # Use a well-known, long-running trial that should always exist
        nct_id = "NCT00001337"
        async with ClinicalTrialsClient() as client:
            result = await client.get_study(nct_id)

        assert isinstance(result, dict)
        proto = result.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        assert ident.get("nctId") == nct_id

    async def test_search_filters_by_status(self):
        """Active recruiting trials only."""
        async with ClinicalTrialsClient() as client:
            results = await client.search_studies(
                condition="melanoma",
                status=["RECRUITING"],
                page_size=5,
            )

        for trial in results:
            assert trial.status == "RECRUITING", (
                f"Expected RECRUITING but got {trial.status}"
            )
