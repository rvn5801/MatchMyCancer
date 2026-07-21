"""Tests for therapy matcher — deterministic, no API calls needed."""

from app.models.biomarker import Biomarker, BiomarkerResult
from app.pipelines.therapy_matcher import (
    load_therapy_database,
    match_therapies,
)


class TestTherapyDatabase:
    def test_database_loads(self):
        therapies = load_therapy_database()
        assert len(therapies) > 0, "Database should not be empty"
        assert all("drug" in t for t in therapies)
        assert all("biomarker" in t for t in therapies)

    def test_database_has_common_drugs(self):
        therapies = load_therapy_database()
        drugs = {t["drug"].lower() for t in therapies}
        # Essential oncology drugs that should be in the database
        assert "osimertinib" in drugs
        assert "trastuzumab" in drugs
        assert "pembrolizumab" in drugs


class TestTherapyMatching:
    def test_matches_egfr_to_multiple_therapies(self):
        biomarkers = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="EGFR",
                    alteration="exon 19 deletion",
                    alteration_type="mutation",
                    raw_text="EGFR exon 19 deletion",
                ),
            ]
        )

        matches = match_therapies(biomarkers)

        assert len(matches) > 0
        drugs = {m["drug"] for m in matches}
        assert "Osimertinib" in drugs

    def test_matches_braf_v600e(self):
        biomarkers = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="BRAF",
                    alteration="V600E",
                    alteration_type="mutation",
                    raw_text="BRAF V600E",
                ),
            ]
        )

        matches = match_therapies(biomarkers)

        drugs = {m["drug"] for m in matches}
        assert "Vemurafenib" in drugs or "Dabrafenib" in drugs

    def test_matches_multiple_biomarkers(self):
        biomarkers = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="EGFR",
                    alteration="L858R",
                    alteration_type="mutation",
                    raw_text="EGFR L858R",
                ),
                Biomarker(
                    gene="ALK",
                    alteration="rearrangement",
                    alteration_type="fusion",
                    raw_text="ALK fusion",
                ),
            ]
        )

        matches = match_therapies(biomarkers)
        drugs = {m["drug"] for m in matches}

        assert len(matches) >= 2  # at least one drug per biomarker
        assert "Osimertinib" in drugs  # EGFR match
        assert "Crizotinib" in drugs or "Alectinib" in drugs  # ALK match

    def test_no_biomarkers_returns_empty(self):
        biomarkers = BiomarkerResult(biomarkers=[])

        matches = match_therapies(biomarkers)

        assert matches == []

    def test_unknown_biomarker_returns_empty(self):
        biomarkers = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="MADEUP_GENE",
                    alteration="fake",
                    raw_text="fake",
                ),
            ]
        )

        matches = match_therapies(biomarkers)

        assert matches == []

    def test_deduplicates_same_drug(self):
        """If EGFR matches osimertinib twice (different alterations), dedupe."""
        biomarkers = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="EGFR",
                    alteration="exon 19 deletion",
                    alteration_type="mutation",
                    raw_text="ex19del",
                ),
                Biomarker(
                    gene="EGFR",
                    alteration="L858R",
                    alteration_type="mutation",
                    raw_text="L858R",
                ),
            ]
        )

        matches = match_therapies(biomarkers)

        drugs = [m["drug"] for m in matches]
        # Osimertinib should appear at most once
        assert drugs.count("Osimertinib") <= 1

    def test_match_quality_field_present(self):
        biomarkers = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="EGFR",
                    alteration="exon 19 deletion",
                    alteration_type="mutation",
                    raw_text="test",
                ),
            ]
        )

        matches = match_therapies(biomarkers)

        for m in matches:
            assert "match_quality" in m
            assert m["match_quality"] in ("exact", "partial")
            assert "matched_biomarker" in m
            assert "patient_alteration" in m

    def test_case_insensitive_matching(self):
        biomarkers = BiomarkerResult(
            biomarkers=[
                Biomarker(
                    gene="egfr",  # lowercase should still match
                    alteration="L858R",
                    alteration_type="mutation",
                    raw_text="egfr",
                ),
            ]
        )

        matches = match_therapies(biomarkers)

        assert len(matches) > 0
