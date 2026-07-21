"""Pytest configuration — loads .env before all tests.

Without this, os.getenv("OPENAI_API_KEY") returns None even when
OPENAI_API_KEY is set in backend/.env, because pytest doesn't
automatically load dotenv files.
"""

from pathlib import Path

from dotenv import load_dotenv

# Load .env from the backend directory (where conftest.py lives)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
