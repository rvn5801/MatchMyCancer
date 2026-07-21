import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.analyze import router as analyze_router
from app.api.v1.extract import router as extract_router
from app.api.v1.uploads import router as upload_router
from app.api.v1.observability import router as observability_router
from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.startup import validate_environment

limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)


async def _daily_trial_refresh():
    """Refresh CT.gov trial freshness once a day.

    ponytail: naive 24h sleep loop, no new dependency. Swap for APScheduler
    or an external cron if you need precise scheduling or missed-run recovery.
    """
    from app.jobs.trial_refresh_job import refresh_all_trials, downrank_stale_trials

    while True:
        try:
            await refresh_all_trials()
            await downrank_stale_trials()
        except Exception:
            logger.exception("Daily trial refresh failed")
        await asyncio.sleep(86_400)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    setup_logging()
    validate_environment()

    refresh_task = None
    if settings.trial_refresh_enabled:
        refresh_task = asyncio.create_task(_daily_trial_refresh())
        logger.info("Daily trial refresh scheduled")

    yield

    if refresh_task:
        refresh_task.cancel()


app = FastAPI(
    title="MatchMyCancer.ai API",
    version="0.2.0",
    description="AI-powered cancer trial navigation and therapy matching platform",
    lifespan=lifespan,
)

# Prometheus metrics
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# CORS - restrict to deployed frontend origin
frontend_origin = settings.frontend_origin or "http://localhost:3000"
# Also allow localhost:3001 for dev
dev_origins = [frontend_origin]
if frontend_origin == "http://localhost:3000":
    dev_origins.append("http://localhost:3001")
app.add_middleware(
    CORSMiddleware,
    allow_origins=dev_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Kill switch check on analyze endpoint
from fastapi import Depends, HTTPException

async def check_analyze_enabled():
    if not settings.analyze_enabled:
        raise HTTPException(503, "Analysis temporarily disabled")

# Register API routers
app.include_router(upload_router, prefix="/api/v1")
app.include_router(extract_router, prefix="/api/v1")
app.include_router(analyze_router, prefix="/api/v1", dependencies=[Depends(check_analyze_enabled)])
app.include_router(observability_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}
