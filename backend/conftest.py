"""Pytest configuration — loads .env and gates network tests.

Without the dotenv load, os.getenv("OPENAI_API_KEY") returns None even
when it's set in backend/.env, because pytest doesn't auto-load dotenv.

Tests marked `@pytest.mark.network` call the live ClinicalTrials.gov API.
They are skipped by default (CI gets rate-limited / is non-deterministic)
and only run when RUN_NETWORK_TESTS=1 is set — same idea as the LLM tests
that self-skip without OPENAI_API_KEY.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env from the backend directory (where conftest.py lives)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: test calls an external network service (opt-in)"
    )


def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_NETWORK_TESTS"):
        return
    skip_network = pytest.mark.skip(
        reason="network test — set RUN_NETWORK_TESTS=1 to run"
    )
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
