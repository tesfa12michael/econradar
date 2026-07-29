"""Data API + /status tests.

The DB session is overridden and the repository layer is monkeypatched, so these
verify routing, parameter handling, and serialization without a live database.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

import repositories
from schemas import (
    AnomalyOut,
    CountryOut,
    IndicatorOptionOut,
    IndicatorSeriesOut,
    IndicatorSummaryOut,
    MapDataOut,
    MapPointOut,
    ObservationOut,
    SourceStatusOut,
)

pytestmark = pytest.mark.usefixtures("override_session")


def test_get_countries(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(_session, region=None):
        return [
            CountryOut(
                country_code="NGA",
                country_name="Nigeria",
                region="Sub-Saharan Africa",
                imf_classification="Emerging",
                flag_emoji="🇳🇬",
            )
        ]

    monkeypatch.setattr(repositories, "list_countries", fake)
    resp = client.get("/api/v1/countries")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["country_code"] == "NGA"
    assert data[0]["flag_emoji"] == "🇳🇬"


def test_get_indicator_series(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(_session, country_code, indicator_code):
        return IndicatorSeriesOut(
            country_code=country_code,
            country_name="Nigeria",
            indicator_code=indicator_code,
            indicator_name="GDP growth (annual %)",
            unit="%",
            source="world_bank",
            observations=[
                ObservationOut(date=dt.date(2024, 1, 1), value=3.2, is_validated=True),
                ObservationOut(date=dt.date(2025, 1, 1), value=4.0, is_validated=True),
            ],
        )

    monkeypatch.setattr(repositories, "get_indicator_series", fake)
    resp = client.get("/api/v1/indicators/nga", params={"code": "NY.GDP.MKTP.KD.ZG"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["country_code"] == "NGA"  # normalized to upper ISO-3
    assert body["source"] == "world_bank"
    assert len(body["observations"]) == 2


def test_get_indicator_series_not_found(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(_session, country_code, indicator_code):
        return None

    monkeypatch.setattr(repositories, "get_indicator_series", fake)
    resp = client.get("/api/v1/indicators/NGA", params={"code": "NOPE"})
    assert resp.status_code == 404


def test_list_country_indicators(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(_session, country_code):
        return [
            IndicatorSummaryOut(
                indicator_code="FP.CPI.TOTL.ZG",
                indicator_name="Inflation, consumer prices (annual %)",
                category="macroeconomic",
                unit="%",
                latest_date=dt.date(2025, 1, 1),
                latest_value=12.5,
            )
        ]

    monkeypatch.setattr(repositories, "list_country_indicators", fake)
    resp = client.get("/api/v1/indicators/NGA")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["indicator_code"] == "FP.CPI.TOTL.ZG"


def test_invalid_country_code(client: TestClient) -> None:
    resp = client.get("/api/v1/indicators/NIGERIA")
    assert resp.status_code == 422


# ── map / anomalies / indicator picker (Phase 2) ─────────────


def test_get_map(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(_s, indicator_code):
        return MapDataOut(
            indicator_code=indicator_code,
            indicator_name="GDP growth (annual %)",
            unit="%",
            source="world_bank",
            points=[
                MapPointOut(
                    country_code="NGA",
                    country_name="Nigeria",
                    value=3.2,
                    date=dt.date(2025, 1, 1),
                    has_anomaly=True,
                ),
            ],
        )

    monkeypatch.setattr(repositories, "get_map_data", fake)
    resp = client.get("/api/v1/map", params={"indicator": "NY.GDP.MKTP.KD.ZG"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["points"][0]["country_code"] == "NGA"
    assert body["points"][0]["has_anomaly"] is True


def test_get_map_unknown_indicator_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(_s, indicator_code):
        return None

    monkeypatch.setattr(repositories, "get_map_data", fake)
    assert client.get("/api/v1/map", params={"indicator": "NOPE"}).status_code == 404


def test_map_requires_an_indicator(client: TestClient) -> None:
    assert client.get("/api/v1/map").status_code == 422


def test_get_anomalies(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake(_s, country_code=None, indicator_code=None, limit=100):
        captured.update(country=country_code, indicator=indicator_code, limit=limit)
        return [
            AnomalyOut(
                country_code="NGA",
                country_name="Nigeria",
                indicator_code="FP.CPI.TOTL.ZG",
                indicator_name="Inflation",
                date=dt.date(2024, 1, 1),
                value=33.2,
                z_score=3.4,
                deviation_type="spike",
            )
        ]

    monkeypatch.setattr(repositories, "list_anomalies", fake)
    resp = client.get("/api/v1/anomalies", params={"country": "nga", "limit": 10})
    assert resp.status_code == 200
    assert resp.json()[0]["deviation_type"] == "spike"
    assert captured["country"] == "NGA"  # normalized to upper ISO-3
    assert captured["limit"] == 10


def test_anomalies_rejects_a_bad_country_code(client: TestClient) -> None:
    assert client.get("/api/v1/anomalies", params={"country": "NIGERIA"}).status_code == 422


def test_anomalies_limit_is_bounded(client: TestClient) -> None:
    assert client.get("/api/v1/anomalies", params={"limit": 9999}).status_code == 422


def test_get_indicator_options(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(_s):
        return [
            IndicatorOptionOut(
                indicator_code="NY.GDP.MKTP.KD.ZG",
                indicator_name="GDP growth (annual %)",
                category="macroeconomic",
                unit="%",
                frequency="annual",
                source="world_bank",
                country_count=217,
            )
        ]

    monkeypatch.setattr(repositories, "list_indicator_options", fake)
    resp = client.get("/api/v1/indicators")
    assert resp.status_code == 200
    assert resp.json()[0]["country_count"] == 217


def test_status_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_countries(_s):
        return 217

    async def fake_indicators(_s):
        return 8

    async def fake_observations(_s):
        return 7843

    async def fake_anomalies(_s):
        return 12

    async def fake_sources(_s):
        return [SourceStatusOut(name="world_bank", is_active=True, last_successful_run=None)]

    monkeypatch.setattr(repositories, "count_countries", fake_countries)
    monkeypatch.setattr(repositories, "count_indicators", fake_indicators)
    monkeypatch.setattr(repositories, "count_observations", fake_observations)
    monkeypatch.setattr(repositories, "count_anomalies", fake_anomalies)
    monkeypatch.setattr(repositories, "list_sources", fake_sources)
    resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "operational"
    assert body["countries_tracked"] == 217
    assert body["observations_tracked"] == 7843
    assert body["anomalies_flagged"] == 12
    assert body["sources"][0]["name"] == "world_bank"
