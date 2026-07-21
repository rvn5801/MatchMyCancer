"""Tests for biomarker extraction pipeline.

These tests require OPENAI_API_KEY to be set (they make real API calls).
When the key is not available, tests are skipped gracefully.
"""

import os

import pytest

from app.models.biomarker import BiomarkerResult
from app.pipelines.biomarker_extractor import extract_biomarkers


def _requires_api_key():
    """Skip test if OPENAI_API_KEY is not configured."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")


class TestBiomarkerExtraction:
    """Happy path: real reports with known biomarkers."""

    def test_extracts_egfr_from_lung_report(self):
        _requires_api_key()

        report = """\
Pathology Report: Lung adenocarcinoma.
Molecular testing shows EGFR exon 19 deletion.
PD-L1 expression: TPS 80%.
ALK rearrangement: negative.
ROS1 fusion: negative.
        """

        result = extract_biomarkers(report)

        assert isinstance(result, BiomarkerResult)
        genes = {b.gene for b in result.biomarkers}
        assert "EGFR" in genes
        assert result.pd_l1_score is not None
        assert "80%" in result.pd_l1_score

    def test_extracts_braf_from_melanoma_report(self):
        _requires_api_key()

        report = """\
Diagnosis: Metastatic melanoma.
BRAF V600E mutation detected by PCR.
NRAS: wild-type.
        """

        result = extract_biomarkers(report)

        genes = {b.gene for b in result.biomarkers}
        assert "BRAF" in genes
        braf = next(b for b in result.biomarkers if b.gene == "BRAF")
        assert braf.alteration is not None
        assert "V600E" in braf.alteration

    def test_extracts_msi_and_tmb(self):
        _requires_api_key()

        report = """\
Colorectal adenocarcinoma.
MSI status: MSI-H (high microsatellite instability).
Tumor Mutational Burden: 25.3 mutations/Mb.
KRAS G12D mutation detected.
        """

        result = extract_biomarkers(report)

        assert result.msi_status is not None
        assert "MSI-H" in result.msi_status.upper()
        assert result.tmb is not None
        assert result.tmb > 10  # MSI-H typically has high TMB
        genes = {b.gene for b in result.biomarkers}
        assert "KRAS" in genes

    def test_multiple_alteration_types(self):
        _requires_api_key()

        report = """\
NGS Panel Results:
- EGFR: L858R mutation (exon 21)
- MET: amplification (copy number = 8)
- ALK: EML4-ALK fusion detected
- TP53: R175H mutation
        """

        result = extract_biomarkers(report)

        assert len(result.biomarkers) >= 4
        alteration_types = {
            b.alteration_type for b in result.biomarkers if b.alteration_type
        }
        # Should detect at least mutation and one other type
        assert "mutation" in alteration_types


class TestEmptyAndEdgeCases:
    """Edge cases that should NOT need an API key."""

    def test_empty_text_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            extract_biomarkers("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            extract_biomarkers("   \n  \t  ")

    def test_no_biomarkers_returns_empty(self):
        _requires_api_key()

        report = "Patient presents with cough. Physical exam unremarkable."

        result = extract_biomarkers(report)

        assert len(result.biomarkers) == 0
        assert result.msi_status is None
        assert result.tmb is None


class TestRawTextProvenance:
    """Verify every extracted biomarker includes its source text."""

    def test_egfr_raw_text_present(self):
        _requires_api_key()

        report = "EGFR exon 19 deletion confirmed by NGS."

        result = extract_biomarkers(report)

        for biomarker in result.biomarkers:
            assert biomarker.raw_text, (
                f"Biomarker {biomarker.gene} missing raw_text"
            )
            assert len(biomarker.raw_text.strip()) > 0
