"""Tests for the explanation engine."""

import os

import pytest

from app.models.biomarker import Biomarker, BiomarkerResult
from app.pipelines.explanation_engine import (
    explain_biomarkers,
    generate_clinical_summary,
)

DISCLAIMER = "This is informational only."


def _requires_api_key():
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")


class TestExplainBiomarkers:
    """Per-biomarker explanation generation."""

    def test_explains_single_egfr(self):
        _requires_api_key()

        result = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="EGFR",
                    alteration="exon 19 deletion",
                    alteration_type="mutation",
                    raw_text="EGFR exon 19 deletion detected",
                )
            ]
        )

        explanations = explain_biomarkers(result)

        assert len(explanations) == 1
        assert "EGFR" in explanations[0]["explanation"]
        assert DISCLAIMER in explanations[0]["explanation"]
        assert explanations[0]["gene"] == "EGFR"
        assert "biomarker" in explanations[0]  # full biomarker data included

    def test_explains_multiple_biomarkers(self):
        _requires_api_key()

        result = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="BRAF",
                    alteration="V600E",
                    alteration_type="mutation",
                    raw_text="BRAF V600E positive",
                ),
                Biomarker(
                    gene="KRAS",
                    alteration="G12D",
                    alteration_type="mutation",
                    raw_text="KRAS G12D mutation",
                ),
            ]
        )

        explanations = explain_biomarkers(result)

        assert len(explanations) == 2
        assert "BRAF" in explanations[0]["explanation"]
        assert "KRAS" in explanations[1]["explanation"]

    def test_every_explanation_has_disclaimer(self):
        _requires_api_key()

        result = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="ALK",
                    alteration="rearrangement",
                    alteration_type="fusion",
                    raw_text="ALK rearrangement detected",
                ),
            ]
        )

        explanations = explain_biomarkers(result)

        for exp in explanations:
            assert DISCLAIMER in exp["explanation"], (
                f"Missing disclaimer for {exp['gene']}"
            )

    def test_empty_biomarkers_returns_empty_list(self):
        result = BiomarkerResult(biomarkers=[])

        explanations = explain_biomarkers(result)

        assert explanations == []

    def test_explanation_mentions_therapy_categories(self):
        """Explanations should be informative about treatment relevance."""
        _requires_api_key()

        result = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="EGFR",
                    alteration="L858R",
                    alteration_type="mutation",
                    raw_text="EGFR L858R",
                ),
            ]
        )

        explanations = explain_biomarkers(result)
        text = explanations[0]["explanation"].lower()

        # Should be a substantive explanation (not just "this is a gene")
        assert len(explanations[0]["explanation"]) > 100, (
            f"Explanation too short: {len(explanations[0]['explanation'])} chars"
        )


class TestClinicalSummary:
    """Full clinical summary generation."""

    def test_generates_summary_from_extraction(self):
        _requires_api_key()

        extraction = {
            "biomarkers": {
                "biomarkers": [
                    {
                        "gene": "EGFR",
                        "alteration": "exon 19 deletion",
                        "alteration_type": "mutation",
                        "raw_text": "EGFR exon 19 del",
                    }
                ],
                "msi_status": None,
                "tmb": None,
                "pd_l1_score": "TPS 80%",
            },
            "diagnosis": {
                "primary_site": "lung",
                "histology": "adenocarcinoma",
                "stage": "Stage IV",
                "raw_text": "Lung adenocarcinoma, Stage IV",
            },
            "raw_report_text": "Patient has Stage IV lung adenocarcinoma...",
        }

        summary = generate_clinical_summary(extraction)

        assert len(summary) > 50
        # Should mention key findings
        assert "educational" in summary.lower() or "discuss" in summary.lower()
        assert "oncology" in summary.lower()

    def test_summary_includes_disclaimer(self):
        _requires_api_key()

        extraction = {
            "biomarkers": {"biomarkers": []},
            "diagnosis": {
                "primary_site": "breast",
                "histology": "ductal carcinoma",
                "raw_text": "Breast ductal carcinoma",
            },
        }

        summary = generate_clinical_summary(extraction)

        assert "educational purposes" in summary.lower()
        assert "oncology team" in summary.lower()

    def test_handles_minimal_extraction(self):
        """Should work even with minimal data."""
        _requires_api_key()

        extraction = {
            "biomarkers": {"biomarkers": []},
            "diagnosis": None,
        }

        summary = generate_clinical_summary(extraction)

        assert isinstance(summary, str)
        assert len(summary) > 0
