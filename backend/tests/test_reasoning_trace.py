"""Tests for the reasoning trace system."""

import pytest

from app.models.reasoning import (
    ReasoningStep,
    RecommendationTrace,
    SourceAttribution,
)
from app.pipelines.reasoning_trace import create_trace


class TestCreateTrace:
    """Trace builder happy path and edge cases."""

    def test_creates_therapy_trace_with_steps_and_sources(self):
        trace = create_trace(
            recommendation_text=(
                "EGFR exon 19 deletion suggests targeted therapy "
                "with an EGFR tyrosine kinase inhibitor."
            ),
            rec_type="therapy",
            steps=[
                {
                    "description": "Extracted EGFR exon 19 deletion from report",
                    "confidence": 0.95,
                },
                {
                    "description": "Checked OncoKB for EGFR evidence levels",
                    "output_data": "Level 1: FDA-recognized",
                    "confidence": 0.90,
                },
            ],
            sources=[
                {
                    "source_name": "OncoKB",
                    "source_url": "https://oncokb.org/gene/EGFR",
                    "relevance": "Level 1 evidence for EGFR exon 19 deletion therapies",
                },
            ],
            confidence=0.85,
        )

        assert isinstance(trace, RecommendationTrace)
        assert trace.recommendation_type == "therapy"
        assert len(trace.reasoning_steps) == 2
        assert trace.reasoning_steps[0].step_number == 1
        assert trace.reasoning_steps[1].step_number == 2
        assert len(trace.sources) == 1
        assert trace.confidence_score == 0.85
        assert trace.recommendation_id  # auto-generated UUID
        assert trace.disclaimer  # auto-generated

    def test_creates_trial_trace(self):
        trace = create_trace(
            recommendation_text="Clinical trial NCT01234567 matches your profile.",
            rec_type="trial",
            steps=[
                {
                    "description": "Searched ClinicalTrials.gov for EGFR + NSCLC",
                    "confidence": 0.80,
                },
            ],
            sources=[
                {
                    "source_name": "ClinicalTrials.gov",
                    "source_url": "https://clinicaltrials.gov/study/NCT01234567",
                    "relevance": "Phase 3 trial for EGFR-mutant NSCLC",
                },
            ],
            confidence=0.75,
        )

        assert trace.recommendation_type == "trial"
        assert len(trace.reasoning_steps) == 1
        assert len(trace.sources) == 1
        assert "ClinicalTrials.gov" in trace.sources[0].source_name

    def test_invalid_rec_type_raises(self):
        with pytest.raises(ValueError, match="must be 'therapy' or 'trial'"):
            create_trace(
                recommendation_text="Some recommendation",
                rec_type="drug",
                steps=[],
                sources=[],
            )

    def test_minimal_trace_no_sources(self):
        """Trace without sources is valid — just lower confidence."""
        trace = create_trace(
            recommendation_text="No targeted therapies found for this profile.",
            rec_type="therapy",
            steps=[
                {
                    "description": "Queried OncoKB for biomarker matches",
                    "output_data": "No matching therapies",
                },
            ],
            sources=[],
            confidence=0.1,
        )

        assert len(trace.sources) == 0
        assert trace.confidence_score == 0.1

    def test_trace_serializes_to_json(self):
        trace = create_trace(
            recommendation_text="BRAF V600E → targeted therapy available.",
            rec_type="therapy",
            steps=[
                {"description": "Extracted BRAF V600E", "confidence": 0.98},
            ],
            sources=[
                {
                    "source_name": "FDA Label",
                    "relevance": "BRAF V600E is an FDA-recognized biomarker",
                },
            ],
            confidence=0.90,
        )

        data = trace.model_dump()

        assert data["recommendation_type"] == "therapy"
        assert data["confidence_score"] == 0.90
        assert len(data["reasoning_steps"]) == 1
        assert len(data["sources"]) == 1
        assert "recommendation_id" in data
        assert "disclaimer" in data
        assert "generated_at" in data

    def test_confidence_bounds_are_enforced(self):
        """Pydantic should reject confidence outside 0.0–1.0."""
        with pytest.raises(Exception):  # ValidationError
            create_trace(
                recommendation_text="test",
                rec_type="therapy",
                steps=[],
                sources=[],
                confidence=1.5,  # invalid
            )

    def test_step_numbers_are_sequential(self):
        trace = create_trace(
            recommendation_text="Sequential reasoning test",
            rec_type="therapy",
            steps=[
                {"description": "First step"},
                {"description": "Second step"},
                {"description": "Third step"},
            ],
            sources=[],
        )

        for i, step in enumerate(trace.reasoning_steps, start=1):
            assert step.step_number == i
