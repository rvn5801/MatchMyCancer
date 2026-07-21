"""Tests for hallucination guardrails."""

import pytest

from app.pipelines.guardrails import (
    calculate_confidence,
    check_for_hallucinated_drugs,
    validate_biomarker_against_source,
)


class TestSourceVerification:
    def test_verifies_egfr_present(self):
        biomarkers = [{"gene": "EGFR", "alteration": "exon 19 deletion"}]
        source = "Patient tested positive for EGFR exon 19 deletion."

        result = validate_biomarker_against_source(biomarkers, source)

        assert result[0]["source_verified"] is True
        assert result[0]["warning"] is None

    def test_flags_missing_biomarker(self):
        biomarkers = [{"gene": "ALK", "alteration": "rearrangement"}]
        source = "EGFR exon 19 deletion detected. BRAF wild-type. No other mutations found."

        result = validate_biomarker_against_source(biomarkers, source)

        assert result[0]["source_verified"] is False
        assert "hallucination" in result[0]["warning"].lower()

    def test_case_insensitive_matching(self):
        biomarkers = [{"gene": "EgFr", "alteration": "L858R"}]
        source = "The patient has an EGFR mutation."

        result = validate_biomarker_against_source(biomarkers, source)

        assert result[0]["source_verified"] is True

    def test_multiple_biomarkers_mixed_results(self):
        biomarkers = [
            {"gene": "EGFR", "alteration": "exon 19 del"},
            {"gene": "MADEUP", "alteration": "fake mutation"},
        ]
        source = "EGFR exon 19 deletion confirmed."

        result = validate_biomarker_against_source(biomarkers, source)

        assert result[0]["source_verified"] is True
        assert result[1]["source_verified"] is False

    def test_empty_source_text(self):
        biomarkers = [{"gene": "EGFR"}]
        source = ""

        result = validate_biomarker_against_source(biomarkers, source)

        assert result[0]["source_verified"] is False
        assert "no source text" in result[0]["warning"].lower()

    def test_empty_biomarker_list(self):
        result = validate_biomarker_against_source([], "Some text")
        assert result == []

    def test_missing_gene_key(self):
        biomarkers = [{"alteration": "some alt"}]
        source = "Some text"

        result = validate_biomarker_against_source(biomarkers, source)

        assert result[0]["source_verified"] is False
        assert "no gene name" in result[0]["warning"].lower()


class TestDrugNameValidation:
    def test_detects_real_drug_suffixes(self):
        text = "Osimertinib may be effective for EGFR T790M."
        unknown = check_for_hallucinated_drugs(text)
        # Without known_drugs, returns all detected
        assert "osimertinib" in unknown

    def test_flags_unknown_drugs_when_set_provided(self):
        text = "Osimertinib and faketinib may be options."
        known = {"osimertinib", "erlotinib", "gefitinib"}

        unknown = check_for_hallucinated_drugs(text, known)

        assert "faketinib" in unknown
        assert "osimertinib" not in unknown

    def test_empty_text_returns_empty(self):
        assert check_for_hallucinated_drugs("") == []
        assert check_for_hallucinated_drugs("   ") == []

    def test_no_drug_like_words(self):
        text = "The patient should discuss options with their oncologist."
        unknown = check_for_hallucinated_drugs(text)
        assert unknown == []

    def test_all_known_drugs_returns_empty(self):
        text = "Osimertinib and bevacizumab are options."
        known = {"osimertinib", "bevacizumab", "pembrolizumab"}

        unknown = check_for_hallucinated_drugs(text, known)

        assert unknown == []


class TestConfidenceScoring:
    def test_full_confidence(self):
        score = calculate_confidence(
            source_verification_rate=1.0,
            has_disclaimer=True,
            source_count=3,
        )
        assert score == 1.0

    def test_zero_confidence(self):
        score = calculate_confidence(
            source_verification_rate=0.0,
            has_disclaimer=False,
            source_count=0,
        )
        assert score == 0.0

    def test_partial_verification(self):
        score = calculate_confidence(
            source_verification_rate=0.75,
            has_disclaimer=True,
            source_count=1,
        )
        # 0.75 * 0.6 + 0.15 + 0.0 + 0.05 = 0.65
        assert score == 0.65

    def test_clamped_to_1_0(self):
        score = calculate_confidence(
            source_verification_rate=1.0,
            has_disclaimer=True,
            source_count=10,  # would be >1.0 without clamping
        )
        assert score == 1.0

    def test_two_sources_bonus(self):
        no_bonus = calculate_confidence(
            source_verification_rate=1.0,
            has_disclaimer=False,
            source_count=1,
        )
        with_bonus = calculate_confidence(
            source_verification_rate=1.0,
            has_disclaimer=False,
            source_count=2,
        )
        # Bonus for ≥2 sources should make it higher
        assert with_bonus > no_bonus
