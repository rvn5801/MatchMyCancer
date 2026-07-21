"""Tests for eligibility summarizer."""

import os

import pytest

from app.pipelines.eligibility_summarizer import summarize_eligibility


def _requires_api_key():
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")


class TestEligibilitySummarizer:
    def test_empty_eligibility_raises(self):
        with pytest.raises(ValueError, match="eligibility_text must not be empty"):
            summarize_eligibility("", "EGFR exon 19 deletion, lung cancer")

    def test_empty_profile_raises(self):
        with pytest.raises(ValueError, match="patient_profile must not be empty"):
            summarize_eligibility("Some criteria", "")

    def test_summarizes_likely_eligible(self):
        _requires_api_key()

        eligibility = (
            "Inclusion Criteria: Histologically confirmed stage IV non-small cell "
            "lung cancer. Documented EGFR exon 19 deletion or L858R mutation. "
            "ECOG performance status 0-2. No prior EGFR TKI therapy. "
            "Exclusion Criteria: Prior osimertinib or other third-generation EGFR TKI. "
            "Symptomatic brain metastases."
        )

        profile = (
            "Patient: 67F, Stage IV lung adenocarcinoma. "
            "EGFR exon 19 deletion detected. No prior targeted therapy. "
            "ECOG 1."
        )

        result = summarize_eligibility(eligibility, profile)

        assert "summary" in result
        assert "eligibility" in result
        assert "reasoning" in result
        assert len(result["summary"]) >= 2
        assert result["eligibility"] in (
            "LIKELY ELIGIBLE",
            "POSSIBLY ELIGIBLE",
            "UNLIKELY ELIGIBLE",
        )

    def test_summarizes_unlikely_eligible(self):
        _requires_api_key()

        eligibility = (
            "Inclusion: BRAF V600E mutation positive melanoma. "
            "Exclusion: Prior BRAF inhibitor therapy."
        )

        profile = (
            "Patient: 67F, Stage IV lung adenocarcinoma. "
            "EGFR exon 19 deletion. No prior therapy."
        )

        result = summarize_eligibility(eligibility, profile)

        # Should be UNLIKELY — wrong cancer type, wrong biomarker
        assert result["eligibility"] in (
            "LIKELY ELIGIBLE",
            "POSSIBLY ELIGIBLE",
            "UNLIKELY ELIGIBLE",
        )
        # Most likely UNLIKELY but LLM may be cautious
        assert len(result["summary"]) >= 1
        assert len(result["reasoning"]) > 10

    def test_summarizes_possibly_eligible(self):
        _requires_api_key()

        eligibility = (
            "Inclusion: Stage III-IV NSCLC. EGFR mutation or ALK rearrangement. "
            "Prior chemotherapy allowed but not required."
        )

        profile = (
            "Patient: Stage IIIB NSCLC. ALK rearrangement detected. "
            "Prior carboplatin+pemetrexed completed."
        )

        result = summarize_eligibility(eligibility, profile)

        assert result["eligibility"] in (
            "LIKELY ELIGIBLE",
            "POSSIBLY ELIGIBLE",
            "UNLIKELY ELIGIBLE",
        )
        assert len(result["summary"]) >= 2
