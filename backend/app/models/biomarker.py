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


class BiomarkerCall(str, Enum):
    """What the test actually found — distinct from what was tested.

    A gene symbol says a marker was examined. Only the call says what the
    answer was. Measured on TCGA-BH-A18H (bilateral breast, HER2-negative on
    both tumours): matching therapy on gene symbol alone returned four
    anti-HER2 drugs for a patient who must not receive any of them.

    POSITIVE:   variant detected / amplified / expression positive
    NEGATIVE:   explicitly absent, not amplified, wild-type, IHC 0 or 1+
    EQUIVOCAL:  borderline, awaiting reflex confirmation (HER2 IHC 2+, no FISH)
    NOT_TESTED: the report says this marker was not assessed
    UNKNOWN:    not stated, or extracted before this field existed

    NOT_TESTED and NEGATIVE are clinically opposite and must not collapse:
    "HER2 was negative" ends the question, "HER2 was never tested" is a gap
    the patient should raise with their oncologist.
    """

    POSITIVE = "positive"
    NEGATIVE = "negative"
    EQUIVOCAL = "equivocal"
    NOT_TESTED = "not_tested"
    UNKNOWN = "unknown"


class Biomarker(BaseModel):
    """A single biomarker finding in the report.

    Covers genomic alterations (EGFR exon 19 deletion, BRAF V600E, ALK fusion)
    and protein/IHC results (ER, PR, HER2), where absence of the target is
    itself the clinically decisive finding.
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
    result: "BiomarkerCall" = Field(
        default=BiomarkerCall.UNKNOWN,
        description=(
            "Whether the target was FOUND. 'positive' when a variant is "
            "detected, amplified, or expression is positive. 'negative' when "
            "explicitly absent, not amplified, wild-type, or IHC 0/1+. "
            "'equivocal' for borderline results with no confirmatory test. "
            "'not_tested' when the report states the marker was not assessed. "
            "Resolve reflex testing: HER2 IHC 2+ with FISH not amplified is "
            "'negative', not 'equivocal'. A detected genomic variant such as "
            "BRAF V600E is 'positive'."
        ),
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
    tumor_label: Optional[str] = Field(
        None,
        description=(
            "Which tumour this result belongs to, matching a TumorInstance "
            "label. Required when the report describes more than one tumour — "
            "a HER2 result means nothing without knowing which specimen it "
            "came from."
        ),
        examples=["Right breast, 9 o'clock", "Part 3: left breast"],
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
        description=(
            "Anatomic site where the tumor ORIGINATED, not where the specimen "
            "was taken. A lymph node biopsy of melanoma is 'skin'."
        ),
        examples=["lung", "breast", "colon", "pancreas", "skin"],
    )
    histology: Optional[str] = Field(
        None,
        description="Histological type",
        examples=["adenocarcinoma", "squamous cell carcinoma", "ductal carcinoma"],
    )
    stage: Optional[str] = Field(
        None,
        description="AJCC stage group only — never TNM (that goes in tnm)",
        examples=["Stage IV", "Stage IIIB", "Stage IB"],
    )
    tnm: Optional[str] = Field(
        None,
        description="TNM classification as reported, space-separated",
        examples=["pT4 pN2 M0", "pT1 pN0 M0", "T2N1M0"],
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


class TumorInstance(CancerDiagnosis):
    """One distinct tumour described in a report.

    Reports routinely describe several: bilateral primaries, multifocal
    disease, a primary plus a metastasis, or separately-parted specimens.

    Measured on TCGA-BH-A18H — two breast primaries, Nottingham grade 2 vs 3,
    pT1b pN0 vs pT1c pN1a, 0/1 vs 2/24 nodes — a single diagnosis object kept
    one and silently discarded the other, and the biomarker list collapsed to
    six unlabelled rows with no way to tell which breast each belonged to.
    """

    label: str = Field(
        ...,
        description=(
            "How the report identifies this tumour. Use the report's own "
            "wording so biomarkers can be matched to it."
        ),
        examples=["Right breast, 9 o'clock", "Part 3: left breast"],
    )
    tumor_size: Optional[str] = Field(
        None,
        description="Largest dimension of the invasive component, as reported",
        examples=["0.8 cm", "13 mm"],
    )
    nodes_examined: Optional[int] = Field(
        None, description="Number of regional lymph nodes examined"
    )
    nodes_positive: Optional[int] = Field(
        None, description="Number of lymph nodes containing metastatic tumour"
    )
    lymphovascular_invasion: Optional[bool] = Field(
        None, description="True if LVI is identified, False if explicitly absent"
    )
    margins: Optional[str] = Field(
        None,
        description="Margin status as reported",
        examples=["negative", "positive", "uninvolved by invasive carcinoma"],
    )


class TumorSet(BaseModel):
    """Container for structured LLM output — every tumour in one report."""

    tumors: List[TumorInstance] = Field(
        default_factory=list,
        description=(
            "One entry per distinct tumour. A bilateral case is TWO entries, "
            "not one with laterality='bilateral'. Do not merge tumours that "
            "have different sizes, grades, stages or node status."
        ),
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
    tumors: List[TumorInstance] = Field(
        default_factory=list,
        description="Every distinct tumour described in the report",
    )
    diagnosis: Optional[CancerDiagnosis] = Field(
        None,
        description=(
            "The clinically dominant tumour, flattened for consumers that "
            "expect one diagnosis (trial condition query, evaluator). Derived "
            "from `tumors` — read `tumors` for the complete picture."
        ),
    )
    treatment_history: Optional[TreatmentHistory] = None
    raw_report_text: Optional[str] = Field(
        None,
        description="First 2000 chars of source text for provenance",
    )
