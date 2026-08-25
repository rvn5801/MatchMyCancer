"""Tests for diagnosis extraction pipeline."""

import os

import pytest

from app.models.biomarker import CancerDiagnosis
from app.pipelines.diagnosis_extractor import (
    dominant_tumor,
    extract_diagnosis,
    extract_tumors,
)


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

    def test_non_clinical_text_returns_none(self):
        """No tumour described means no diagnosis.

        Contract change: this previously returned a CancerDiagnosis with every
        field None but raw_text set to the input, which asserts a diagnosis
        exists where none does. None is the honest answer, and every consumer
        already treats diagnosis as optional.
        """
        _requires_api_key()

        assert extract_diagnosis("The weather is nice today.") is None


class TestMultipleTumors:
    """A report can describe more than one tumour — see TCGA-BH-A18H."""

    BILATERAL = """\
FINAL DIAGNOSIS:
PART 1: BREAST, RIGHT AT 9 O'CLOCK, SEGMENTAL MASTECTOMY -
A. INVASIVE DUCTAL CARCINOMA, NO SPECIAL TYPE.
B. NOTTINGHAM GRADE 2.
C. THE INVASIVE TUMOR MEASURES 0.8 CM IN LARGEST DIMENSION.
T STAGE, PATHOLOGIC: pT1b   N STAGE, PATHOLOGIC: pN0
LYMPH NODES POSITIVE: 0   LYMPH NODES EXAMINED: 1

PART 3: BREAST, LEFT AT 12 O'CLOCK, SEGMENTAL MASTECTOMY -
A. INVASIVE DUCTAL CARCINOMA, NO SPECIAL TYPE.
B. NOTTINGHAM GRADE 3.
C. THE INVASIVE TUMOR MEASURES 1.3 CM IN LARGEST DIMENSION.
I. FOCAL LYMPHOVASCULAR SPACE INVASION IS IDENTIFIED.
T STAGE, PATHOLOGIC: pT1c   N STAGE, PATHOLOGIC: pN1a
LYMPH NODES POSITIVE: 2   LYMPH NODES EXAMINED: 24
"""

    def test_bilateral_yields_two_tumors(self):
        _requires_api_key()

        tumors = extract_tumors(self.BILATERAL)

        assert len(tumors) == 2, f"expected 2 tumours, got {[t.label for t in tumors]}"
        assert {t.laterality and t.laterality.lower() for t in tumors} == {
            "right",
            "left",
        }

    def test_node_counts_are_not_shared_between_tumors(self):
        """Copying one tumour's node status onto the other is the classic error."""
        _requires_api_key()

        tumors = extract_tumors(self.BILATERAL)
        positives = sorted(t.nodes_positive for t in tumors if t.nodes_positive is not None)

        assert positives == [0, 2], f"expected 0 and 2 positive nodes, got {positives}"

    def test_dominant_is_the_node_positive_tumor(self):
        """The left breast drives care despite being listed second."""
        _requires_api_key()

        dominant = dominant_tumor(extract_tumors(self.BILATERAL))

        assert dominant is not None
        assert dominant.laterality is not None
        assert "left" in dominant.laterality.lower()
