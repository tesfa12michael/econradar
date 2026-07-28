"""Shared test fixtures.

Tests run without a database: the app boots with no DATABASE_URL (scheduler stays
stopped, /health reports not_configured), and DB-backed routes get their session
dependency overridden with a no-op while the repository functions are monkeypatched.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from config import settings
from db import get_session
from main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # Hermetic boot: ignore any developer-local .env so the app comes up with no
    # database and the scheduler stopped, matching the clean-CI environment.
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    with TestClient(app) as c:
        yield c


async def _null_session():
    yield None


@pytest.fixture
def override_session() -> Iterator[None]:
    """Replace the DB session dependency with a no-op (routes' repo calls are mocked)."""
    app.dependency_overrides[get_session] = _null_session
    yield
    app.dependency_overrides.pop(get_session, None)
