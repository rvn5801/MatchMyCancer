"""Tests for the clinical extraction API endpoint."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _requires_api_key():
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")


class TestExtractEndpoint:
    """Happy path and error handling."""

    @pytest.mark.asyncio
    async def test_extract_returns_200_with_biomarkers(self):
        _requires_api_key()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/extract",
                json={
                    "document_text": (
                        "Lung adenocarcinoma. EGFR exon 19 deletion. "
                        "PD-L1 TPS 80%. ALK negative."
                    ),
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "clinical_data" in data
        cd = data["clinical_data"]
        assert "biomarkers" in cd
        assert len(cd["biomarkers"]["biomarkers"]) > 0

    @pytest.mark.asyncio
    async def test_extract_returns_400_for_empty_text(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/extract",
                json={"document_text": ""},
            )

        assert response.status_code == 400
        assert "must not be empty" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_extract_returns_422_for_missing_field(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/extract",
                json={},
            )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_extract_returns_422_for_invalid_type(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/extract",
                json={"document_text": 123},
            )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_extract_returns_clinicalextraction_shape(self):
        _requires_api_key()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/extract",
                json={
                    "document_text": (
                        "Colorectal adenocarcinoma. KRAS G12D mutation. "
                        "MSI-H. Stage IIIB."
                    ),
                },
            )

        data = response.json()
        cd = data["clinical_data"]

        # Verify the structure matches ClinicalExtraction
        assert "biomarkers" in cd
        assert "diagnosis" in cd
        assert "raw_report_text" in cd

        # BiomarkerResult structure
        bm = cd["biomarkers"]
        assert "biomarkers" in bm  # List[Biomarker]
        assert "msi_status" in bm
        assert "tmb" in bm
        assert "pd_l1_score" in bm

    @pytest.mark.asyncio
    async def test_health_endpoint_still_works(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
