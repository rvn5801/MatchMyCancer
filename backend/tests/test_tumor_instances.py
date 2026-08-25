"""Tumour-instance separation.

Regression guard for a measured defect. TCGA-BH-A18H describes two breast
primaries — right 9 o'clock (grade 2, pT1b pN0, 0/1 nodes) and left 12 o'clock
(grade 3, pT1c pN1a, 2/24 nodes, LVI present). A single CancerDiagnosis kept
one and silently discarded the other, and picking the first-listed tumour
would have queried trials for the less advanced disease.
"""

import pytest

from app.models.biomarker import CancerDiagnosis, TumorInstance, TumorSet
from app.pipelines.diagnosis_extractor import (
    _as_diagnosis,
    _size_mm,
    dominant_tumor,
)


def _tumor(label, **kw):
    kw.setdefault("raw_text", label)
    return TumorInstance(label=label, **kw)


# The two tumours as the report states them.
RIGHT = _tumor(
    "Right breast, 9 o'clock",
    primary_site="breast",
    histology="invasive ductal carcinoma",
    tnm="pT1b pN0",
    grade="Nottingham grade 2",
    laterality="right",
    tumor_size="0.8 cm",
    nodes_examined=1,
    nodes_positive=0,
    lymphovascular_invasion=False,
    margins="negative",
)
LEFT = _tumor(
    "Left breast, 12 o'clock",
    primary_site="breast",
    histology="invasive ductal carcinoma",
    tnm="pT1c pN1a",
    grade="Nottingham grade 3",
    laterality="left",
    tumor_size="1.3 cm",
    nodes_examined=24,
    nodes_positive=2,
    lymphovascular_invasion=True,
    margins="negative",
)


class TestSizeParsing:
    @pytest.mark.parametrize(
        "text,expected",
        [("0.8 cm", 8.0), ("13 mm", 13.0), ("1.3 cm", 13.0), ("8 mm", 8.0)],
    )
    def test_units_normalise_to_mm(self, text, expected):
        assert _size_mm(text) == expected

    @pytest.mark.parametrize("text", [None, "", "not stated", "large"])
    def test_unparseable_is_zero_not_an_error(self, text):
        assert _size_mm(text) == 0.0


class TestDominantTumor:
    def test_node_positive_wins_over_first_listed(self):
        """The real trap: right breast is listed first but left drives care."""
        assert dominant_tumor([RIGHT, LEFT]) is LEFT

    def test_order_does_not_matter(self):
        assert dominant_tumor([LEFT, RIGHT]) is LEFT

    def test_larger_wins_when_nodes_tie(self):
        small = _tumor("a", tumor_size="5 mm", nodes_positive=0)
        big = _tumor("b", tumor_size="30 mm", nodes_positive=0)
        assert dominant_tumor([small, big]) is big

    def test_single_tumor_is_dominant(self):
        assert dominant_tumor([RIGHT]) is RIGHT

    def test_empty_is_none(self):
        assert dominant_tumor([]) is None

    def test_missing_node_counts_do_not_crash(self):
        a = _tumor("a")
        b = _tumor("b", nodes_positive=1)
        assert dominant_tumor([a, b]) is b


class TestFlattening:
    def test_as_diagnosis_preserves_fields(self):
        d = _as_diagnosis(LEFT)
        assert isinstance(d, CancerDiagnosis)
        assert (d.primary_site, d.histology, d.tnm, d.laterality) == (
            "breast",
            "invasive ductal carcinoma",
            "pT1c pN1a",
            "left",
        )

    def test_flattening_drops_tumor_only_fields(self):
        """Node counts have no home in CancerDiagnosis — read `tumors` for them."""
        assert not hasattr(_as_diagnosis(LEFT), "nodes_positive")


class TestTumorSet:
    def test_both_tumors_survive(self):
        """A single diagnosis object could only ever hold one of these."""
        s = TumorSet(tumors=[RIGHT, LEFT])
        assert len(s.tumors) == 2
        assert {t.grade for t in s.tumors} == {
            "Nottingham grade 2",
            "Nottingham grade 3",
        }
        assert {t.nodes_positive for t in s.tumors} == {0, 2}

    def test_empty_set_is_valid(self):
        assert TumorSet().tumors == []

    def test_label_is_required(self):
        """Without a label, biomarkers cannot be attributed to a tumour."""
        with pytest.raises(ValueError):
            TumorInstance(raw_text="x")
