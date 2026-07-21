"""
Tests for the document upload endpoint.

Key testing concepts:
- ASGITransport: Tests FastAPI in-process, no network/port needed
- Happy path + error path: Always test both
- Real PDFs via fitz: Fake bytes won't work because the upload
  endpoint auto-processes through PyMuPDF
"""

import uuid as uuid_lib

import fitz
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def create_test_pdf(path: str, text: str) -> None:
    """Create a valid one-page PDF with given text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=12)
    doc.save(path)
    doc.close()


@pytest.mark.asyncio
async def test_upload_pdf_succeeds(tmp_path):
    """Happy path: Upload a valid PDF. Extraction should auto-run."""
    # Create a real PDF for the test
    pdf_path = tmp_path / "report.pdf"
    create_test_pdf(str(pdf_path), "EGFR mutation detected in lung adenocarcinoma")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with open(pdf_path, "rb") as f:
            files = {"file": ("report.pdf", f, "application/pdf")}
            response = await client.post("/api/v1/upload", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["document_id"]) == 36
    assert data["extraction_method"] == "pymupdf"
    assert "EGFR" in data["extracted_preview"]


@pytest.mark.asyncio
async def test_upload_rejects_exe(tmp_path):
    """Error path: Reject non-medical MIME types."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files = {"file": ("virus.exe", b"malicious", "application/x-msdownload")}
        response = await client.post("/api/v1/upload", files=files)

    assert response.status_code == 415
    assert "Unsupported" in response.json()["detail"]


@pytest.mark.asyncio
async def test_upload_handles_empty_file(tmp_path):
    """Edge case: 0-byte file with PDF MIME type. Should return error status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files = {"file": ("empty.pdf", b"", "application/pdf")}
        response = await client.post("/api/v1/upload", files=files)

    # Should not crash — returns an error status instead
    assert response.status_code in (200, 422)
    data = response.json()
    if response.status_code == 200:
        # File saved but extraction failed
        assert data["status"] in ("error", "low_text")


@pytest.mark.asyncio
async def test_upload_preserves_uuid_format(tmp_path):
    """document_id should always be a valid UUID v4."""
    pdf_path = tmp_path / "uuid_test.pdf"
    create_test_pdf(str(pdf_path), "HER2 negative")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with open(pdf_path, "rb") as f:
            files = {"file": ("uuid_test.pdf", f, "application/pdf")}
            response = await client.post("/api/v1/upload", files=files)

    doc_id = response.json()["document_id"]
    parsed = uuid_lib.UUID(doc_id)
    assert parsed.version == 4  # UUID4 (random)


@pytest.mark.asyncio
async def test_upload_extracts_page_count(tmp_path):
    """Multi-page PDF: page_count should be in metadata."""
    pdf_path = str(tmp_path / "multi.pdf")
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((50, 50), f"Page {i+1}", fontsize=12)
    doc.save(pdf_path)
    doc.close()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with open(pdf_path, "rb") as f:
            files = {"file": ("multi.pdf", f, "application/pdf")}
            response = await client.post("/api/v1/upload", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["page_count"] == 3
    assert data["status"] == "success"
