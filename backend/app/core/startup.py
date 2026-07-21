"""Startup validation for environment and dependencies.

Checks required configuration on server startup so missing API keys
are caught immediately rather than failing on the first request.
"""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def validate_environment() -> bool:
    """Check required environment variables and dependencies.

    Called once on FastAPI startup. Returns True if everything
    is configured correctly, raises RuntimeError otherwise.
    """
    warnings: list[str] = []

    # Critical: API key for LLM extraction
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. "
            "Copy backend/.env.template to backend/.env and add your key."
        )

    logger.info("OPENAI_API_KEY: configured")

    # Check optional but recommended
    if not settings.chroma_persist_dir:
        warnings.append("CHROMA_PERSIST_DIR not set — vector search will use default path")

    # Check Tesseract binary availability
    try:
        import shutil
        if not shutil.which("tesseract"):
            warnings.append(
                "Tesseract OCR binary not found — OCR for scanned documents "
                "will not work. Install with: sudo apt install tesseract-ocr"
            )
        else:
            logger.info("Tesseract OCR: available")
    except Exception:
        pass

    # Log warnings
    for w in warnings:
        logger.warning(w)

    logger.info(
        "Environment validated: model=%s, chroma=%s",
        settings.openai_model,
        settings.chroma_persist_dir,
    )

    return True
