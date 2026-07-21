"""Biomarker and clinical extraction schemas.

These Pydantic models define the structured output that the LLM extraction
pipeline produces. They serve double duty:
  1. API contract — what the extract endpoint returns
  2. LLM output parsing — langchain's with_structured_output() uses
     these schemas to force the LLM into producing valid JSON

Design decisions:
  - Every field has a raw_text for provenance (which sentence was this from?)
  - Optional fields everywhere — real reports are incomplete
  - Flat models (no deep nesting) because LLMs produce better JSON with
    shallower schema structures
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


class ConfidenceTier(str, Enum):
    """Confidence tier — replaces fabricated 0.00-1.00 scores.

    HIGHEST: exact source span found in document text
    MEDIUM: fuzzy/partial source span found
    LOW: no source span (LLM claim without provenance)
    """
    HIGHEST = "HIGHEST"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Biomarker(BaseModel):
    """A single genomic alteration found in the report.

    Example: EGFR exon 19 deletion, BRAF V600E, ALK fusion
    """

    gene: str = Field(
        ...,
        description="Gene symbol (HGNC format): EGFR, BRAF, KRAS, ALK, etc.",
        examples=["EGFR", "BRAF"],
    )
    alteration: Optional[str] = Field(
        None,
        description="Specific alteration: 'exon 19 deletion', 'V600E', 'fusion'",
        examples=["exon 19 deletion", "V600E"],
    )
    alteration_type: Optional[str] = Field(
        None,
        description="Category of alteration",
        examples=["mutation", "amplification", "fusion", "expression", "deletion"],
    )
    significance: Optional[str] = Field(
        None,
        description="Clinical significance if stated in report",
        examples=["pathogenic", "variant of unknown significance", "benign"],
    )
    test_method: Optional[str] = Field(
        None,
        description="How this was detected",
        examples=["NGS", "IHC", "FISH", "PCR", "Sanger sequencing"],
    )
    raw_text: str = Field(
        ...,
        description="Verbatim text from the report supporting this finding",
    )
    source_span: Optional[tuple[int, int]] = Field(
        None,
        description="(start_char, end_char) in original document text for provenance",
    )
    confidence: ConfidenceTier = Field(
        default=ConfidenceTier.LOW,
        description="Confidence tier based on provenance quality",
    )


class BiomarkerResult(BaseModel):
    """Aggregated biomarker findings from a report.

    Includes individual gene alterations plus summary-level genomic markers
    (MSI status, TMB, PD-L1) that are reported separately from named genes.
    """

    biomarkers: List[Biomarker] = Field(
        default_factory=list,
        description="Individual gene-level alterations detected",
    )
    msi_status: Optional[str] = Field(
        None,
        description="Microsatellite instability status",
        examples=["MSS", "MSI-H", "MSI-L"],
    )
    tmb: Optional[float] = Field(
        None,
        description="Tumor mutational burden in mutations/megabase",
        examples=[12.4],
    )
    pd_l1_score: Optional[str] = Field(
        None,
        description="PD-L1 expression result",
        examples=["TPS 80%", "CPS 5", "negative", "positive (>1%)"],
    )


class CancerDiagnosis(BaseModel):
    """Cancer diagnosis extracted from a pathology or clinical report."""

    primary_site: Optional[str] = Field(
        None,
        description="Anatomic site of primary tumor",
        examples=["lung", "breast", "colon", "pancreas"],
    )
    histology: Optional[str] = Field(
        None,
        description="Histological type",
        examples=["adenocarcinoma", "squamous cell carcinoma", "ductal carcinoma"],
    )
    stage: Optional[str] = Field(
        None,
        description="Disease stage (AJCC or other staging system)",
        examples=["Stage IV", "T2N1M0", "Stage IIIB"],
    )
    grade: Optional[str] = Field(
        None,
        description="Tumor grade if reported",
        examples=["Grade 2", "moderately differentiated", "high grade"],
    )
    laterality: Optional[str] = Field(
        None,
        description="Left, right, bilateral if applicable",
        examples=["left", "right", "bilateral"],
    )
    raw_text: str = Field(
        ...,
        description="Verbatim report text supporting the diagnosis",
    )
    source_span: Optional[tuple[int, int]] = Field(
        None,
        description="(start_char, end_char) in original document text for provenance",
    )
    confidence: ConfidenceTier = Field(
        default=ConfidenceTier.LOW,
        description="Confidence tier based on provenance quality",
    )


class TreatmentHistoryEntry(BaseModel):
    """A single prior or current treatment."""

    therapy: Optional[str] = Field(
        None,
        description="Therapy name or regimen",
        examples=["carboplatin + pemetrexed", "osimertinib"],
    )
    therapy_type: Optional[str] = Field(
        None,
        description="Category of therapy",
        examples=["chemotherapy", "targeted therapy", "immunotherapy", "radiation"],
    )
    dates: Optional[str] = Field(
        None,
        description="Treatment timeframe as stated in report",
        examples=["2023-01 to 2023-06"],
    )
    response: Optional[str] = Field(
        None,
        description="Best response achieved",
        examples=["partial response", "stable disease", "progressive disease"],
    )
    reason_stopped: Optional[str] = Field(
        None,
        description="Why treatment ended if stated",
        examples=["progression", "toxicity", "completed planned course"],
    )


class TreatmentHistory(BaseModel):
    """Prior treatment history extracted from the report."""

    treatments: List[TreatmentHistoryEntry] = Field(default_factory=list)
    raw_text: Optional[str] = Field(
        None,
        description="Verbatim text section covering treatment history",
    )


class ClinicalExtraction(BaseModel):
    """Complete clinical extraction from a single oncology report.

    This is the top-level model — everything the extraction pipeline
    produces from one document.
    """

    biomarkers: BiomarkerResult = Field(default_factory=lambda: BiomarkerResult())
    diagnosis: Optional[CancerDiagnosis] = None
    treatment_history: Optional[TreatmentHistory] = None
    raw_report_text: Optional[str] = Field(
        None,
        description="First 2000 chars of source text for provenance",
    )
