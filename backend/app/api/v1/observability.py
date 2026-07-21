"""Observability endpoints: spend, health, version."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import redis.asyncio as redis
from app.core.config import settings
from app.core.metrics import get_redis

router = APIRouter(tags=["observability"])


@router.get("/spend")
async def get_spend(redis_client: redis.Redis = Depends(get_redis)):
    """Get current daily spend in USD."""
    today = __import__("datetime").date.today().isoformat()
    key = f"spend:{today}"
    value = await redis_client.get(key)
    return {
        "date": today,
        "spend_usd": float(value) if value else 0.0,
        "ceiling_usd": getattr(settings, "spend_ceiling_usd", 50.0),
    }


@router.get("/stats")
async def get_stats():
    """Anonymous, non-PHI usage counters (no report content stored)."""
    from app.core.metrics import get_stats as _get_stats
    return await _get_stats()


@router.get("/version")
async def get_version():
    """Get API version and git commit (commit injected at build time)."""
    import os
    return {
        "version": "0.2.0",
        "commit": os.getenv("GIT_COMMIT", "unknown"),
    }


@router.get("/ready")
async def readiness():
    """Kubernetes readiness probe."""
    # Check Redis connectivity
    try:
        r = await get_redis()
        await r.ping()
    except Exception:
        raise HTTPException(503, "Redis unavailable")
    return {"status": "ready"}


class DetailedHealth(BaseModel):
    """Extended health check with dependency status."""
    status: str
    version: str
    redis: str
    chroma: str
    openai_key_present: bool


@router.get("/health/detailed", response_model=DetailedHealth)
async def detailed_health():
    """Extended health check with all dependencies (no relational DB — stateless)."""
    import chromadb

    redis_status = "ok"
    chroma_status = "ok"

    # Check Redis (spend ceiling + metrics)
    try:
        r = await get_redis()
        await r.ping()
    except Exception:
        redis_status = "error"

    # Check ChromaDB (trial index)
    try:
        client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        client.heartbeat()
    except Exception:
        chroma_status = "error"

    return DetailedHealth(
        status="ok" if all(s == "ok" for s in [redis_status, chroma_status]) else "degraded",
        version="0.2.0",
        redis=redis_status,
        chroma=chroma_status,
        openai_key_present=bool(settings.openai_api_key),
    )