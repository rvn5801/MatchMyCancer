"""Tests for diagnosis extraction pipeline."""

import os

import pytest

from app.models.biomarker import CancerDiagnosis
from app.pipelines.diagnosis_extractor import extract_diagnosis


def _requires_api_key():
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")


class TestDiagnosisExtraction:
    """Happy path: real pathology reports."""

    def test_extracts_lung_adenocarcinoma(self):
        _requires_api_key()

        report = """\
Lung, left lower lobe, core needle biopsy:
Invasive adenocarcinoma, acinar predominant.
Moderately differentiated (Grade 2).
pT2a N1 M0 — Stage IIB (AJCC 8th edition).
        """

        result = extract_diagnosis(report)

        assert isinstance(result, CancerDiagnosis)
        assert result.primary_site is not None
        assert "lung" in result.primary_site.lower()
        assert result.histology is not None
        assert "adenocarcinoma" in result.histology.lower()
        assert result.stage is not None

    def test_extracts_breast_cancer_diagnosis(self):
        _requires_api_key()

        report = """\
Right breast, ultrasound-guided core biopsy:
Invasive ductal carcinoma, Nottingham Grade 3 (poorly differentiated).
ER positive (95%), PR positive (80%), HER2 negative (1+).
Clinical stage: cT2 N1 M0.
        """

        result = extract_diagnosis(report)

        assert result.primary_site is not None
        assert "breast" in result.primary_site.lower()
        assert result.histology is not None
        assert "ductal" in result.histology.lower()
        assert result.grade is not None

    def test_extracts_colorectal_cancer(self):
        _requires_api_key()

        report = """\
Sigmoid colon, endoscopic biopsy:
Moderately differentiated adenocarcinoma.
Invasive into submucosa.
pT1 N0 Mx.
        """

        result = extract_diagnosis(report)

        assert result.primary_site is not None
        assert "colon" in result.primary_site.lower()
        assert result.histology is not None
        assert "adenocarcinoma" in result.histology.lower()

    def test_partial_report_missing_stage(self):
        """Reports often lack staging info — extractor should handle this."""
        _requires_api_key()

        report = """\
Pancreas, fine needle aspiration:
Ductal adenocarcinoma.
        """

        result = extract_diagnosis(report)

        assert result.primary_site is not None
        assert result.histology is not None
        # Stage may be None — that's OK for incomplete reports
        assert result.raw_text is not None


class TestEdgeCases:
    def test_empty_text_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            extract_diagnosis("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            extract_diagnosis("   \n  ")

    def test_non_clinical_text_handled(self):
        _requires_api_key()

        report = "The weather is nice today."

        result = extract_diagnosis(report)

        # Should still return a valid object, just with mostly None fields
        assert isinstance(result, CancerDiagnosis)
        assert result.raw_text is not None
