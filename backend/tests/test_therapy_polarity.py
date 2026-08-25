"""Therapy matching must respect the biomarker RESULT, not just the gene.

Regression guard for a measured defect. On TCGA-BH-A18H — a real bilateral
breast case, HER2-negative on both tumours (right: IHC 2+/FISH not amplified;
left: IHC 1+) — the extractor correctly returned ERBB2 with result "negative",
and the matcher recommended trastuzumab, pertuzumab, trastuzumab emtansine and
trastuzumab deruxtecan anyway, because it compared only the gene symbol.
"""

import pytest

from app.models.biomarker import Biomarker, BiomarkerCall, BiomarkerResult
from app.pipelines.therapy_matcher import is_actionable, match_therapies


def _bm(gene, *, result=BiomarkerCall.UNKNOWN, alteration=None, significance=None):
    return Biomarker(
        gene=gene,
        alteration=alteration,
        alteration_type="expression",
        significance=significance,
        result=result,
        raw_text=f"{gene} {alteration or ''}".strip(),
    )


class TestIsActionable:
    def test_positive_call_is_actionable(self):
        assert is_actionable(_bm("ERBB2", result=BiomarkerCall.POSITIVE))

    def test_negative_call_is_not(self):
        assert not is_actionable(_bm("ERBB2", result=BiomarkerCall.NEGATIVE))

    def test_equivocal_is_not_actionable(self):
        """HER2 IHC 2+ with no FISH has not established the target."""
        assert not is_actionable(_bm("ERBB2", result=BiomarkerCall.EQUIVOCAL))

    @pytest.mark.parametrize(
        "alteration",
        [
            "negative",
            "not amplified",
            "non-amplified",
            "no amplification",
            "not detected",
            "wild-type",
            "wild type",
            "absent",
            "equivocal",
        ],
    )
    def test_unknown_call_falls_back_to_free_text(self, alteration):
        """A missing structured call must not defeat the guard."""
        assert not is_actionable(_bm("ERBB2", alteration=alteration))

    @pytest.mark.parametrize(
        "gene,alteration",
        [
            ("BRAF", "V600E"),
            ("EGFR", "exon 19 deletion"),
            ("ALK", "fusion"),
            ("CDKN2A", "loss"),
            ("BRCA1", "deletion"),
        ],
    )
    def test_genuine_alterations_still_match(self, gene, alteration):
        """No regression: 'loss' and 'deletion' ARE the actionable finding."""
        assert is_actionable(_bm(gene, alteration=alteration))

    def test_negative_significance_blocks(self):
        assert not is_actionable(
            _bm("ERBB2", alteration="2+", significance="negative for amplification")
        )

    def test_not_tested_is_not_actionable(self):
        """'not tested' and 'negative' are opposite findings, both untreatable."""
        assert not is_actionable(_bm("ERBB2", result=BiomarkerCall.NOT_TESTED))

    @pytest.mark.parametrize(
        "significance",
        [
            "variant of unknown significance",
            "variant of uncertain significance",
            "VUS",
            "uncertain significance",
            "benign",
            "likely benign",
        ],
    )
    def test_vus_blocks_even_when_detected(self, significance):
        """A detected variant is still not a treatment target if uninterpretable."""
        assert not is_actionable(
            _bm(
                "EGFR",
                result=BiomarkerCall.POSITIVE,
                alteration="p.L861X",
                significance=significance,
            )
        )

    @pytest.mark.parametrize("significance", ["pathogenic", "likely pathogenic"])
    def test_pathogenic_significance_still_matches(self, significance):
        """No regression: pathogenic is exactly what should match."""
        assert is_actionable(
            _bm(
                "EGFR",
                result=BiomarkerCall.POSITIVE,
                alteration="exon 19 deletion",
                significance=significance,
            )
        )

    @pytest.mark.parametrize("alteration", ["pending", "QNS", "quantity not sufficient"])
    def test_unresolved_results_are_not_actionable(self, alteration):
        assert not is_actionable(_bm("ERBB2", alteration=alteration))


class TestMatchTherapies:
    def test_her2_negative_gets_no_anti_her2_therapy(self):
        """The core defect: four wrong drugs for a HER2-negative patient."""
        result = BiomarkerResult(
            biomarkers=[_bm("ERBB2", result=BiomarkerCall.NEGATIVE, alteration="negative")]
        )
        assert match_therapies(result) == []

    def test_vus_gets_no_targeted_therapy(self):
        """Detected EGFR variant of unknown significance must not match osimertinib."""
        result = BiomarkerResult(
            biomarkers=[
                _bm(
                    "EGFR",
                    result=BiomarkerCall.POSITIVE,
                    alteration="p.L861X",
                    significance="variant of unknown significance",
                )
            ]
        )
        assert match_therapies(result) == []

    def test_her2_positive_still_matches(self):
        """The guard must not break the case the feature exists for."""
        result = BiomarkerResult(
            biomarkers=[
                _bm("ERBB2", result=BiomarkerCall.POSITIVE, alteration="amplification")
            ]
        )
        drugs = {t["drug"] for t in match_therapies(result)}
        assert "Trastuzumab" in drugs

    def test_tcga_bh_a18h_full_case(self):
        """The real report: 3 markers x 2 tumours, all correctly non-actionable.

        ER+ and PR+ are genuinely positive but ESR1/PGR are absent from the
        therapy database, so the honest output is zero therapies — not four
        contraindicated ones.
        """
        biomarkers = BiomarkerResult(
            biomarkers=[
                _bm("ESR1", result=BiomarkerCall.POSITIVE, alteration="positive"),
                _bm("PGR", result=BiomarkerCall.POSITIVE, alteration="positive"),
                _bm("ERBB2", result=BiomarkerCall.NEGATIVE, alteration="negative"),
                _bm("ESR1", result=BiomarkerCall.POSITIVE, alteration="positive"),
                _bm("PGR", result=BiomarkerCall.POSITIVE, alteration="positive"),
                _bm("ERBB2", result=BiomarkerCall.NEGATIVE, alteration="negative"),
            ]
        )
        matched = match_therapies(biomarkers)
        assert matched == [], f"expected no therapies, got {[t['drug'] for t in matched]}"

    def test_mixed_tumours_only_positive_matches(self):
        """One HER2+ tumour and one HER2- tumour still yields anti-HER2 therapy."""
        biomarkers = BiomarkerResult(
            biomarkers=[
                _bm("ERBB2", result=BiomarkerCall.NEGATIVE, alteration="negative"),
                _bm("ERBB2", result=BiomarkerCall.POSITIVE, alteration="amplification"),
            ]
        )
        assert {t["drug"] for t in match_therapies(biomarkers)}

    def test_default_call_is_unknown(self):
        """Existing extractions predate the field and must keep working."""
        assert Biomarker(gene="BRAF", raw_text="BRAF V600E").result is BiomarkerCall.UNKNOWN
