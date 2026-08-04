"""Tests for the ClinicalTrials.gov condition query builder.

Regression guard: real melanoma pathology reports describe a lymph-node
specimen, and the extractor used to return primary_site="lymph node". The old
builder turned that into "lymph node cancer" and searched the wrong trials.
"""

from types import SimpleNamespace

from app.api.v1.analyze import _build_condition


def _dx(site=None, histology=None):
    return SimpleNamespace(primary_site=site, histology=histology)


class TestBuildCondition:
    def test_site_and_histology_combine(self):
        assert _build_condition(_dx("lung", "adenocarcinoma")) == "lung adenocarcinoma"

    def test_histology_used_when_site_missing(self):
        # Metastatic specimen with no stated origin — "melanoma" beats "cancer"
        assert _build_condition(_dx(None, "melanoma")) == "melanoma"

    def test_site_only_gets_cancer_suffix(self):
        assert _build_condition(_dx("lung", None)) == "lung cancer"

    def test_no_duplicate_site_when_histology_contains_it(self):
        assert _build_condition(_dx("skin", "skin melanoma")) == "skin melanoma"

    def test_cancer_terms_not_double_suffixed(self):
        for hist in ["melanoma", "carcinoma", "sarcoma", "lymphoma", "glioma"]:
            assert _build_condition(_dx(None, hist)) == hist

    def test_empty_diagnosis_falls_back(self):
        assert _build_condition(_dx()) == "cancer"
        assert _build_condition(None) == "cancer"

    def test_blank_strings_treated_as_missing(self):
        assert _build_condition(_dx("  ", "  ")) == "cancer"
