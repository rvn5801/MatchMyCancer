from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class DocumentMetadata(BaseModel):
    """Metadata about an uploaded document.

    This is a Pydantic model, not a SQLAlchemy model. Why?
    - We may NOT persist to a database (zero-storage architecture)
    - Pydantic handles serialization to JSON automatically
    - Validates types at the API boundary (defense in depth)
    """

    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    page_count: Optional[int] = None
    extraction_method: Optional[str] = None


class UploadResponse(BaseModel):
    """What the API returns after a successful upload.

    Note: document_id is a UUID string, not an integer.
    Why? Sequential IDs leak how many documents you've processed.
    UUIDs are unpredictable and collision-resistant without a database.
    """

    document_id: str
    status: str
    metadata: DocumentMetadata
    # Preview of extracted text (first 3000 chars) — for display only.
    extracted_preview: Optional[str] = None
    # Full extracted text — returned to the client so it can be sent to
    # /analyze. Never persisted server-side (zero-PHI, ADR-001).
    extracted_text: Optional[str] = None
    extraction_method: Optional[str] = None
