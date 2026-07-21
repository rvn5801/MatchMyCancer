"""Reasoning trace builder.

Creates RecommendationTrace objects that capture the AI's full
decision chain. Every therapy or trial recommendation gets wrapped
in a trace so patients and clinicians can see exactly how the AI
arrived at its suggestion.

Usage:
    trace = create_trace(
        recommendation_text="EGFR exon 19 deletion → osimertinib...",
        rec_type="therapy",
        steps=[
            {"description": "Extracted EGFR exon 19 deletion", "confidence": 0.95},
            {"description": "Queried OncoKB for EGFR therapies", "confidence": 0.90},
        ],
        sources=[
            {"source_name": "OncoKB", "relevance": "Level 1 evidence for EGFR"},
        ],
        confidence=0.85,
    )
"""

import logging

from app.models.reasoning import (
    ReasoningStep,
    RecommendationTrace,
    SourceAttribution,
)

logger = logging.getLogger(__name__)


def create_trace(
    recommendation_text: str,
    rec_type: str,
    steps: list[dict],
    sources: list[dict],
    confidence: float = 0.0,
) -> RecommendationTrace:
    """Build a recommendation with full reasoning trace.

    Args:
        recommendation_text: The actual recommendation (e.g., "EGFR T790M
            mutation suggests osimertinib may be effective").
        rec_type: "therapy" or "trial".
        steps: List of dicts with keys matching ReasoningStep fields
            (description required, input_data/output_data/confidence optional).
        sources: List of dicts with keys matching SourceAttribution fields
            (source_name and relevance required, source_url optional).
        confidence: Overall confidence score (0.0–1.0).

    Returns:
        RecommendationTrace with full audit trail.
    """
    if rec_type not in ("therapy", "trial"):
        raise ValueError(f"rec_type must be 'therapy' or 'trial', got '{rec_type}'")

    reasoning_steps = [
        ReasoningStep(
            step_number=i + 1,
            description=step["description"],
            input_data=step.get("input_data"),
            output_data=step.get("output_data"),
            confidence=step.get("confidence", 0.0),
        )
        for i, step in enumerate(steps)
    ]

    source_attributions = [
        SourceAttribution(
            source_name=src["source_name"],
            source_url=src.get("source_url"),
            relevance=src["relevance"],
        )
        for src in sources
    ]

    trace = RecommendationTrace(
        recommendation_text=recommendation_text,
        recommendation_type=rec_type,
        confidence_score=confidence,
        reasoning_steps=reasoning_steps,
        sources=source_attributions,
    )

    logger.info(
        "Created %s trace with %d steps, %d sources (confidence=%.2f)",
        rec_type,
        len(reasoning_steps),
        len(source_attributions),
        confidence,
    )

    return trace
