"""Scoring taxonomy for the corpus evaluation.

The critical property under test: a pipeline that faithfully reports what the
document says (pNX when no nodes were examined) must never be scored as wrong
against a registry that recorded N0 from outside the document. Grounded in
TCGA-B1-A656, where exactly that happens on N, M and stage simultaneously.
"""

import pytest

from app.evaluation.evaluate_corpus import (
    m_component,
    n_component,
    norm_registry_tnm,
    norm_stage,
    score_histology,
    score_site,
    score_stratified,
    stated_in_text,
    t_component,
)

# Real embedded-layer text fragments from TCGA-B1-A656.
KIRP_TEXT = """FINAL DIAGNOSIS: RENAL MASS, LEFT, PARTIAL NEPHRECTOMY -
RENAL CELL CARCINOMA. PATHOLOGIC TNM STAGE (AJCC 7th EDITION): pTla NX MX.
HISTOLOGIC TYPE: Papillary renal cell carcinoma
PATHOLOGIC STAGING (pTNM): pTla pNX"""


class TestComponents:
    @pytest.mark.parametrize("tnm,expect", [
        ("pT1a pNX pMX", "T1A"),
        ("pT1b pN0", "T1B"),
        ("T2 N1 M0", "T2"),
        ("ypT0 N0", "T0"),
        (None, None),
        ("no tnm here", None),
    ])
    def test_t_component(self, tnm, expect):
        assert t_component(tnm) == expect

    def test_n_and_m_components(self):
        assert n_component("pT1c pN1a M0") == "N1A"
        assert n_component("pT1a pNX pMX") == "NX"
        assert m_component("pT1a pNX pMX") == "MX"
        assert m_component("T2 N0 M0") == "M0"

    @pytest.mark.parametrize("value,expect", [
        ("N0 (I-)", "N0"),          # registry decorations stripped
        ("T1A", "T1A"),
        ("N1MI", "N1MI"),
        (None, None),
    ])
    def test_registry_normalisation(self, value, expect):
        assert norm_registry_tnm(value) == expect

    @pytest.mark.parametrize("value,expect", [
        ("STAGE IIA", "IIA"),
        ("Stage I", "I"),
        ("STAGE X", None),           # not a stage group
        ("STAGE I/II (NOS)", None),
        (None, None),
    ])
    def test_stage_normalisation(self, value, expect):
        assert norm_stage(value) == expect


class TestStatedInText:
    def test_t1a_found_despite_ocr_l_for_1(self):
        """The document says pTla (OCR); registry says T1A. Must count as stated."""
        assert stated_in_text("T", "T1A", KIRP_TEXT)

    def test_n0_not_stated_when_document_says_nx(self):
        assert not stated_in_text("N", "N0", KIRP_TEXT)

    def test_stage_i_not_stated(self):
        assert not stated_in_text("stage", "STAGE I", KIRP_TEXT)

    def test_stage_boundary_i_vs_iii(self):
        assert not stated_in_text("stage", "STAGE I", "Findings: Stage IIIA disease.")
        assert stated_in_text("stage", "STAGE IIIA", "Findings: Stage IIIA disease.")

    def test_arabic_stage_form(self):
        assert stated_in_text("stage", "STAGE 2A" if False else "STAGE IIA",
                              "clinical stage 2a carcinoma")


class TestStratifiedScoring:
    """The TCGA-B1-A656 rows, as the scorer must call them."""

    def test_faithful_nx_is_not_an_error(self):
        assert score_stratified("N", "N0", "NX", KIRP_TEXT) == "unstated_declined"

    def test_faithful_mx_is_not_an_error(self):
        assert score_stratified("M", "M0", "MX", KIRP_TEXT) == "unstated_declined"

    def test_derived_stage_declined(self):
        assert score_stratified("stage", "STAGE I", None, KIRP_TEXT) == "unstated_declined"

    def test_stated_value_scored_normally(self):
        text = "pT2 pN1 M0, consistent with Stage IIB."
        assert score_stratified("N", "N1", "N1", text) == "stated_correct"
        assert score_stratified("N", "N1", "N2", text) == "stated_wrong"

    def test_unstated_but_invented_value_is_flagged(self):
        """Pipeline asserting N0 when the document never says it: not faithful."""
        assert score_stratified("N", "N0", "N0", KIRP_TEXT) == "unstated_agrees"
        assert score_stratified("N", "N0", "N1", KIRP_TEXT) == "unstated_differs"


class TestSiteScoring:
    def test_kidney_correct(self):
        assert score_site("C64.9", "kidney") == "correct"

    def test_breast_wrong(self):
        assert score_site("C50.9", "lung") == "wrong"

    def test_specimen_site_never_scored_as_error(self):
        """Registry C77.3 = axillary node specimen; pipeline answering the
        origin (skin) is the behaviour we built, not a mistake."""
        assert score_site("C77.3", "skin") == "specimen_site_origin_given"

    def test_unmapped_code_is_a_bucket_not_a_crash(self):
        assert score_site("C42.1", "bone marrow") == "unmapped_code"


class TestHistologyScoring:
    def test_translated_match(self):
        assert score_histology("8260/3", "papillary renal cell carcinoma") == "correct"

    def test_melanoma_codes_accept_melanoma(self):
        for code in ("8720/3", "8721/3", "8743/3"):
            assert score_histology(code, "malignant melanoma") == "correct"

    def test_wrong_histology(self):
        assert score_histology("8520/3", "ductal carcinoma") == "wrong"

    def test_unmapped_counted_loudly(self):
        assert score_histology("9999/3", "anything") == "unmapped_code"
