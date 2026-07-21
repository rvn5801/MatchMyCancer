"""Clinical extraction API endpoint.

POST /api/v1/extract — accepts document text and returns structured
clinical data (biomarkers + diagnosis).
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.pipelines.clinical_extraction import extract_clinical_data

logger = logging.getLogger(__name__)

router = APIRouter()


class ExtractRequest(BaseModel):
    """Request body for clinical extraction."""
    document_text: str = Field(
        ...,
        description="Full text extracted from the uploaded document",
        examples=["EGFR exon 19 deletion detected by NGS. Lung adenocarcinoma."],
    )


class ExtractResponse(BaseModel):
    """Response from clinical extraction."""
    status: str = Field(
        default="success",
        description="Status of the extraction",
    )
    clinical_data: dict = Field(
        ...,
        description="Structured ClinicalExtraction as a dict",
    )


@router.post("/extract", response_model=ExtractResponse)
async def extract_clinical(request: ExtractRequest):
    """Extract biomarkers and diagnosis from document text.

    Accepts the raw text from a processed medical document (PDF extraction
    or OCR output) and returns structured clinical data including biomarkers,
    cancer diagnosis, and supporting evidence.

    The extraction is powered by a large language model using structured
    output — results are validated against the Pydantic schema before
    returning.
    """
    try:
        result = extract_clinical_data(request.document_text)
    except ValueError as e:
        logger.warning("Extract request rejected: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error("Extract configuration error: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Extraction service not configured. Check OPENAI_API_KEY.",
        )
    except Exception as e:
        logger.exception("Unexpected extraction error")
        raise HTTPException(
            status_code=500,
            detail=f"Extraction failed: {str(e)}",
        )

    logger.info(
        "Extract complete: %d biomarkers",
        len(result.biomarkers.biomarkers),
    )

    return ExtractResponse(
        status="success",
        clinical_data=result.model_dump(),
    )
