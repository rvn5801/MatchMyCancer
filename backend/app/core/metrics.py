"""Anonymous, non-PHI usage metrics via Redis counters.

Reuses the same Redis the spend ceiling uses — no relational DB, no
report content ever stored. Best-effort: metric failures never break
analysis (Redis is optional infrastructure).
"""

import datetime
import logging

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Shared Redis client. Uses REDIS_URL (rediss://… for Upstash/managed,
    incl. TLS + auth) when set, else falls back to host/port."""
    global _client
    if _client is None:
        if settings.redis_url:
            _client = redis.from_url(settings.redis_url, decode_responses=True)
        else:
            _client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                decode_responses=True,
            )
    return _client


async def record_analysis() -> None:
    """Increment the anonymous analysis counters. Never raises."""
    try:
        r = await get_redis()
        today = datetime.date.today().isoformat()
        await r.incr(f"metrics:analyses:{today}")
        await r.incr("metrics:analyses:total")
    except Exception as e:  # pragma: no cover - best-effort
        logger.debug("metric record skipped: %s", e)


async def get_stats() -> dict:
    """Return anonymous usage counts (no PHI)."""
    r = await get_redis()
    today = datetime.date.today().isoformat()
    return {
        "date": today,
        "analyses_today": int(await r.get(f"metrics:analyses:{today}") or 0),
        "analyses_total": int(await r.get("metrics:analyses:total") or 0),
    }
