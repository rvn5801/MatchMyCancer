"""
Document upload endpoint.

Interview-ready concepts demonstrated:
- Async I/O: await file.read() yields the event loop so other
  requests aren't blocked during disk I/O
- Content-type whitelisting (set for O(1) lookup)
- Size validation BEFORE writing to disk (don't waste I/O on bad files)
- In-memory processing — zero PHI persistence (ponytail: C1)
- HTTP status code semantics (400=client error, 413=payload too large)
"""

import uuid
from fastapi import APIRouter, File, HTTPException, UploadFile, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.models.document import DocumentMetadata, UploadResponse
from app.pipelines.document_pipeline import process_document

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

# Set for O(1) membership testing
ALLOWED_TYPES: set[str] = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
}

# 10MB — smaller than before since we hold in memory
MAX_SIZE_BYTES: int = 10 * 1024 * 1024


@router.post("/upload", response_model=UploadResponse)
@limiter.limit("5/minute")
async def upload_document(request: Request, file: UploadFile = File(...)):
    """
    Accept a medical document upload — zero PHI persistence.

    Flow:
    1. Validate MIME type — reject anything not medical-document-shaped
    2. Read file into memory — can't trust Content-Length header
    3. Validate size — prevent memory exhaustion
    4. Process in-memory bytes through extraction pipeline (NO disk write)
    5. Return document_id + extraction preview
    """
    # Step 1: Validate MIME type
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,  # 415 Unsupported Media Type
            detail=f"Unsupported file type: {file.content_type}. "
            f"Accepted: {', '.join(sorted(ALLOWED_TYPES))}",
        )

    # Step 2: Read entire file into memory
    contents = await file.read()

    # Step 3: Validate size
    if len(contents) > MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=413,  # 413 Payload Too Large
            detail=f"File exceeds {MAX_SIZE_BYTES // (1024 * 1024)}MB limit",
        )

    # Step 4: Process in-memory (ponytail: no disk I/O)
    doc_id = str(uuid.uuid4())
    try:
        proc_result = process_document(contents, file.content_type)
    except Exception as e:
        proc_result = {
            "status": "error",
            "message": f"Extraction failed: {str(e)}",
            "full_text": "",
            "page_count": None,
            "extraction_method": None,
            "confidence": None,
        }

    # Step 5: Return response with extraction preview
    return UploadResponse(
        document_id=doc_id,
        status=proc_result.get("status", "uploaded"),
        metadata=DocumentMetadata(
            filename=file.filename,
            content_type=file.content_type,
            size_bytes=len(contents),
            page_count=proc_result.get("page_count"),
            extraction_method=proc_result.get("extraction_method"),
        ),
        extracted_preview=proc_result.get("full_text", "")[:3000],
        extracted_text=proc_result.get("full_text", ""),
        extraction_method=proc_result.get("extraction_method"),
    )
