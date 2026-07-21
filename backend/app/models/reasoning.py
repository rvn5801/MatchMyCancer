"""Reasoning trace and source attribution models.

These models capture the AI's decision-making process for each
recommendation — what steps it took, what sources it consulted,
and how confident it is. This is the foundation of explainable AI:

  1. ReasoningStep: each atomic step in the decision chain
  2. SourceAttribution: which external source backs a claim
  3. RecommendationTrace: the complete audit trail for one suggestion

Why this matters for MatchMyCancer:
  - Patients (and their doctors) need to trust recommendations
  - Regulatory scrutiny requires auditable AI decisions
  - Debugging: when a recommendation is wrong, the trace shows why
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ReasoningStep(BaseModel):
    """One atomic step in the AI's decision chain.

    Example: "Extracted EGFR exon 19 deletion from report" →
             "Checked OncoKB for EGFR therapies" →
             "Found 3 FDA-approved targeted therapies"
    """

    step_number: int = Field(..., description="Order in the reasoning chain")
    description: str = Field(
        ..., description="What this step does in plain language"
    )
    input_data: Optional[str] = Field(
        None, description="Data consumed by this step (truncated)"
    )
    output_data: Optional[str] = Field(
        None, description="Result produced by this step (truncated)"
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence in this step's output",
    )


class SourceAttribution(BaseModel):
    """Links a claim to the external source that supports it.

    Example: "FDA label for osimertinib lists EGFR exon 19 deletion
    as an approved indication" → source: fda.gov/label/...
    """

    source_name: str = Field(
        ...,
        description="Human-readable name: 'FDA Label', 'OncoKB', 'ClinicalTrials.gov'",
        examples=["FDA Label", "OncoKB", "ClinicalTrials.gov", "NCCN Guidelines"],
    )
    source_url: Optional[str] = Field(
        None,
        description="URL to the specific source document",
    )
    retrieval_date: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this source was retrieved",
    )
    relevance: str = Field(
        ...,
        description="Why this source supports the recommendation",
    )


class RecommendationTrace(BaseModel):
    """Complete audit trail for one AI-generated recommendation.

    Ties together: what was recommended, why (the reasoning steps),
    and where the evidence comes from (the sources).
    """

    recommendation_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique ID for this recommendation",
    )
    recommendation_text: str = Field(
        ...,
        description="The actual recommendation shown to the patient",
    )
    recommendation_type: str = Field(
        ...,
        description="'therapy' (FDA-approved) or 'trial' (clinical trial)",
        examples=["therapy", "trial"],
    )
    confidence_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Overall confidence (0.0–1.0)",
    )
    reasoning_steps: List[ReasoningStep] = Field(
        default_factory=list,
        description="Ordered steps the AI took to reach this recommendation",
    )
    sources: List[SourceAttribution] = Field(
        default_factory=list,
        description="External sources backing this recommendation",
    )
    disclaimer: str = Field(
        default=(
            "This is an AI-generated suggestion based on available data. "
            "Verify all recommendations with a licensed medical professional."
        ),
        description="Standard medical disclaimer",
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this trace was generated",
    )
