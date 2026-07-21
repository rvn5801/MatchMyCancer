import logging
import sys

from app.core.config import settings


def setup_logging() -> None:
    """Configure structured logging for the entire application.

    Called once on startup. Sets format, level, and silences
    noisy third-party loggers.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Silence noisy libraries
    for lib in ("httpx", "httpcore", "chromadb", "urllib3", "openai", "asyncio"):
        logging.getLogger(lib).setLevel(logging.WARNING)
