"""Full pipeline analysis endpoint.

POST /api/v1/analyze — runs the complete MatchMyCancer pipeline synchronously.
GET  /api/v1/analyze/stream — SSE stream of the same pipeline.
"""

import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
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

    condition = (
        extraction.diagnosis.primary_site
        if extraction.diagnosis and extraction.diagnosis.primary_site
        else "cancer"
    )
    if "cancer" not in condition.lower():
        condition = f"{condition} cancer"

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
async def analyze_report(request: AnalyzeRequest):
    """Run the full MatchMyCancer pipeline on document text."""
    result = await _run_pipeline(request.document_text)
    return AnalyzeResponse(**result)


@router.post("/analyze/stream")
async def analyze_stream(request: StreamRequest):
    """SSE stream of the pipeline execution."""
    async def event_generator():
        import json
        text = request.text
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

            condition = (
                extraction.diagnosis.primary_site
                if extraction.diagnosis and extraction.diagnosis.primary_site
                else "cancer"
            )
            if "cancer" not in condition.lower():
                condition = f"{condition} cancer"

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

        except ValueError as e:
            yield f"data: {json.dumps({'stage': 'error', 'message': str(e)})}\n\n"
        except RuntimeError as e:
            yield f"data: {json.dumps({'stage': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
