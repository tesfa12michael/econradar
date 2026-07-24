"""Root + /health endpoint tests (no database required)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_root(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "EconRadar API"
    assert body["health"] == "/health"


def test_health_ok_without_db(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # No DATABASE_URL is configured under test.
    assert body["database"] == "not_configured"
    assert body["scheduler"] in {"stopped", "disabled"}
    assert body["version"]
