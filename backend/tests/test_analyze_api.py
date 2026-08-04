"""Tests for the analyze endpoints: SSE error frames and rate limiting."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """slowapi keeps counters in memory across tests — clear between tests."""
    from app.core.limiter import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.mark.asyncio
async def test_stream_emits_error_frame_on_unexpected_exception(monkeypatch):
    """Any exception must produce a terminal error event, not a dead stream.

    Regression guard: the handler used to catch only ValueError/RuntimeError,
    so an httpx/OpenAI error killed the stream with no event and the UI hung.
    """
    def _boom(_text):
        raise TypeError("unexpected failure")  # neither ValueError nor RuntimeError

    monkeypatch.setattr("app.api.v1.analyze.extract_clinical_data", _boom)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/analyze/stream", json={"text": "report"})
        assert res.status_code == 200
        body = res.text

    assert '"stage": "error"' in body
    assert "unexpected failure" in body


@pytest.mark.asyncio
async def test_analyze_is_rate_limited(monkeypatch):
    """The expensive endpoint must return 429 once the per-IP limit is hit.

    The pipeline is stubbed with a valid response — a raising stub would
    propagate through ASGITransport and abort the loop before the limit.
    """
    async def _stub_pipeline(_text):
        return {
            "extraction": {},
            "explanations": [],
            "clinical_summary": "",
            "therapies": [],
            "trials": [],
            "guardrails": {},
            "meta": {},
        }

    monkeypatch.setattr("app.api.v1.analyze._run_pipeline", _stub_pipeline)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        statuses = []
        for _ in range(12):  # limit is 10/hour
            res = await client.post("/api/v1/analyze", json={"document_text": "x"})
            statuses.append(res.status_code)

    assert 200 in statuses, f"expected some requests to succeed, got {statuses}"
    assert 429 in statuses, f"expected a 429 within 12 requests, got {statuses}"
