"""Full pipeline analysis endpoint.

POST /api/v1/analyze — runs the complete MatchMyCancer pipeline synchronously.
GET  /api/v1/analyze/stream — SSE stream of the same pipeline.
"""

import json
import logging
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.limiter import limiter
from app.core.metrics import record_analysis
from app.models.biomarker import ClinicalExtraction
from app.pipelines.clinical_extraction import extract_clinical_data
from app.pipelines.explanation_engine import (
    explain_biomarkers,
    generate_clinical_summary,
)
from app.pipelines.guardrails import calculate_confidence, validate_biomarker_against_source
from app.pipelines.therapy_matcher import match_therapies
from app.pipelines.trial_matcher import find_matching_trials

logger = logging.getLogger(__name__)

router = APIRouter()

# Each analysis costs ~10 LLM calls, so this endpoint is the spend risk.
ANALYZE_RATE_LIMIT = "10/hour"

# Words that already name a malignancy, so " cancer" shouldn't be appended.
_CANCER_TERMS = (
    "cancer", "carcinoma", "melanoma", "sarcoma", "lymphoma",
    "leukemia", "myeloma", "glioma", "blastoma", "mesothelioma",
)


def _build_condition(diagnosis) -> str:
    """Build the ClinicalTrials.gov condition query from a diagnosis.

    Uses histology as well as site: reports that describe only a metastatic
    specimen often have no stated primary site, and querying a bare "cancer"
    returns noise. "melanoma" is a far better query than "cancer", and
    "lung adenocarcinoma" better than "lung".

    ponytail: string concatenation, no ontology mapping. Swap in an ICD-O/
    MeSH lookup if condition matching needs to be precise.
    """
    site = ((diagnosis.primary_site if diagnosis else None) or "").strip()
    hist = ((diagnosis.histology if diagnosis else None) or "").strip()

    if site and hist:
        # Avoid "lung lung adenocarcinoma" when histology already names the site
        condition = hist if site.lower() in hist.lower() else f"{site} {hist}"
    else:
        condition = hist or site

    if not condition:
        return "cancer"
    if not any(term in condition.lower() for term in _CANCER_TERMS):
        condition = f"{condition} cancer"
    return condition


class AnalyzeRequest(BaseModel):
    document_text: str = Field(
        ...,
        min_length=1,
        description="Full text from a medical report (PDF extraction or OCR output)",
    )


class StreamRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Full text from a medical report")


class AnalyzeResponse(BaseModel):
    status: str = "success"
    extraction: dict
    explanations: list[dict]
    clinical_summary: str
    therapies: list[dict]
    trials: list[dict]
    guardrails: dict
    meta: dict


async def _run_pipeline(text: str):
    """Core pipeline - returns dict, used by both sync and stream endpoints.

    The kill switch (ANALYZE_ENABLED) is enforced by the router-level
    dependency in main.py, so it is not re-checked here.
    """
    extraction = extract_clinical_data(text)
    extraction_dict = extraction.model_dump()

    explanations = explain_biomarkers(extraction.biomarkers)
    summary = generate_clinical_summary(extraction_dict)

    therapies = match_therapies(extraction.biomarkers)

    condition = _build_condition(extraction.diagnosis)

    trials_raw = await find_matching_trials(
        biomarkers=extraction.biomarkers,
        condition=condition,
    )
    trials = [t.model_dump() for t in trials_raw]

    biomarker_dicts = extraction_dict["biomarkers"]["biomarkers"]
    validated = validate_biomarker_against_source(biomarker_dicts, text)

    verified_count = sum(1 for v in validated if v["source_verified"])
    verification_rate = verified_count / len(validated) if validated else 1.0

    confidence = calculate_confidence(
        source_verification_rate=verification_rate,
        has_disclaimer=True,
        source_count=len(therapies) + (1 if trials else 0),
    )

    guardrails = {
        "source_verification": {
            "verified": verified_count,
            "total": len(validated),
            "rate": verification_rate,
            "details": validated,
        },
        "confidence_score": confidence,
        "warnings": [v["warning"] for v in validated if v.get("warning")],
    }

    meta = {
        "biomarkers_found": len(extraction.biomarkers.biomarkers),
        "therapies_matched": len(therapies),
        "trials_found": len(trials),
        "pipeline_version": "0.1.0",
    }

    await record_analysis()

    return {
        "extraction": extraction_dict,
        "explanations": explanations,
        "clinical_summary": summary,
        "therapies": therapies,
        "trials": trials,
        "guardrails": guardrails,
        "meta": meta,
    }


@router.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit(ANALYZE_RATE_LIMIT)
async def analyze_report(request: Request, body: AnalyzeRequest):
    """Run the full MatchMyCancer pipeline on document text."""
    result = await _run_pipeline(body.document_text)
    return AnalyzeResponse(**result)


@router.post("/analyze/stream")
@limiter.limit(ANALYZE_RATE_LIMIT)
async def analyze_stream(request: Request, body: StreamRequest):
    """SSE stream of the pipeline execution."""
    async def event_generator():
        text = body.text
        try:
            # Yield progress events
            yield f"data: {json.dumps({'stage': 'extract', 'message': 'Extracting biomarkers...'})}\n\n"
            extraction = extract_clinical_data(text)
            extraction_dict = extraction.model_dump()
            yield f"data: {json.dumps({'stage': 'explain', 'message': 'Generating explanations...', 'extraction': extraction_dict})}\n\n"

            explanations = explain_biomarkers(extraction.biomarkers)
            summary = generate_clinical_summary(extraction_dict)
            yield f"data: {json.dumps({'stage': 'therapy', 'message': 'Matching therapies...', 'explanations': explanations, 'summary': summary})}\n\n"

            therapies = match_therapies(extraction.biomarkers)
            yield f"data: {json.dumps({'stage': 'trial', 'message': 'Searching clinical trials...', 'therapies': therapies})}\n\n"

            condition = _build_condition(extraction.diagnosis)

            trials_raw = await find_matching_trials(
                biomarkers=extraction.biomarkers,
                condition=condition,
            )
            trials = [t.model_dump() for t in trials_raw]
            yield f"data: {json.dumps({'stage': 'guardrails', 'message': 'Running guardrails...', 'trials': trials})}\n\n"

            biomarker_dicts = extraction_dict["biomarkers"]["biomarkers"]
            validated = validate_biomarker_against_source(biomarker_dicts, text)

            verified_count = sum(1 for v in validated if v["source_verified"])
            verification_rate = verified_count / len(validated) if validated else 1.0

            confidence = calculate_confidence(
                source_verification_rate=verification_rate,
                has_disclaimer=True,
                source_count=len(therapies) + (1 if trials else 0),
            )

            guardrails = {
                "source_verification": {
                    "verified": verified_count,
                    "total": len(validated),
                    "rate": verification_rate,
                    "details": validated,
                },
                "confidence_score": confidence,
                "warnings": [v["warning"] for v in validated if v.get("warning")],
            }

            meta = {
                "biomarkers_found": len(extraction.biomarkers.biomarkers),
                "therapies_matched": len(therapies),
                "trials_found": len(trials),
                "pipeline_version": "0.1.0",
            }

            await record_analysis()
            yield f"data: {json.dumps({'stage': 'complete', 'extraction': extraction_dict, 'explanations': explanations, 'clinical_summary': summary, 'therapies': therapies, 'trials': trials, 'guardrails': guardrails, 'meta': meta})}\n\n"

        except Exception as e:
            # Any escaping exception kills the stream with no error event and
            # the UI spins forever — always emit a terminal error frame.
            logger.exception("Analysis stream failed")
            yield f"data: {json.dumps({'stage': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
