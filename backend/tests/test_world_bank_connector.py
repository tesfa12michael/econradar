"""World Bank connector: normalization edge cases, pagination, validation, live API."""

from __future__ import annotations

import contextlib
import datetime as dt

import httpx
import pytest

from connectors import NormalizationError, SkipRecord, ValidationError, WorldBankConnector
from schemas import TimeSeriesRecord


def _row(**overrides) -> dict:
    row = {
        "countryiso3code": "NGA",
        "indicator": {"id": "NY.GDP.MKTP.KD.ZG", "value": "GDP growth (annual %)"},
        "country": {"id": "NG", "value": "Nigeria"},
        "date": "2025",
        "value": 4.01,
        "unit": "",
    }
    row.update(overrides)
    return row


def test_normalize_annual_row() -> None:
    c = WorldBankConnector()
    rec = c.normalize(_row())
    assert rec.country_code == "NGA"
    assert rec.indicator_code == "NY.GDP.MKTP.KD.ZG"
    assert rec.date == dt.date(2025, 1, 1)
    assert rec.value == pytest.approx(4.01)
    assert rec.source_name == "world_bank"
    # display name captured for catalog upsert
    assert c.indicator_display_name("NY.GDP.MKTP.KD.ZG") == "GDP growth (annual %)"


def test_normalize_null_value_is_skipped() -> None:
    c = WorldBankConnector()
    with pytest.raises(SkipRecord):
        c.normalize(_row(value=None))


def test_normalize_aggregate_row_rejected() -> None:
    # Aggregates/regions have no ISO-3 country code.
    c = WorldBankConnector()
    with pytest.raises(NormalizationError):
        c.normalize(_row(countryiso3code=""))


def test_normalize_subannual_dates_supported() -> None:
    """Phase 1 rejected sub-annual periods; Phase 2 parses them (BIS/FRED/GEM need it)."""
    c = WorldBankConnector()

    monthly = c.normalize(_row(date="2025M03"))
    assert monthly.date == dt.date(2025, 3, 1)
    assert monthly.frequency == "monthly"

    quarterly = c.normalize(_row(date="2025Q4"))
    assert quarterly.date == dt.date(2025, 10, 1)
    assert quarterly.frequency == "quarterly"

    annual = c.normalize(_row(date="2025"))
    assert annual.date == dt.date(2025, 1, 1)
    assert annual.frequency == "annual"


def test_normalize_unparseable_date_rejected() -> None:
    c = WorldBankConnector()
    with pytest.raises(NormalizationError):
        c.normalize(_row(date="not-a-date"))


def test_normalize_falls_back_to_country_id() -> None:
    """DataBank source=15 leaves countryiso3code empty and puts ISO-3 in country.id."""
    c = WorldBankConnector()
    rec = c.normalize(_row(countryiso3code="", country={"id": "NGA", "value": "Nigeria"}))
    assert rec.country_code == "NGA"


def test_normalize_aggregate_row_still_rejected() -> None:
    """Neither field carries an ISO-3 code for regional aggregates."""
    c = WorldBankConnector()
    with pytest.raises(NormalizationError):
        c.normalize(_row(countryiso3code="", country={"id": "ZJ", "value": "Latin America"}))


@pytest.mark.parametrize("code", ["ARB", "EMU", "WLD", "SSF", "LMY"])
def test_three_letter_aggregates_are_skipped(code: str) -> None:
    """ARB/EMU/WLD are well-formed ISO-3 *shapes* but are not countries.

    Storing them silently corrupts every world average on the dashboard, so the
    connector filters against the World Bank's own country index instead of a
    shape check. Regression guard for the rows purged by migration 0007.
    """
    c = WorldBankConnector()
    c._known_countries = {"NGA", "USA"}
    with pytest.raises(SkipRecord):
        c.normalize(_row(countryiso3code=code))


def test_real_country_passes_the_index_check() -> None:
    c = WorldBankConnector()
    c._known_countries = {"NGA", "USA"}
    assert c.normalize(_row(countryiso3code="NGA")).country_code == "NGA"


def test_index_check_is_skipped_when_the_index_is_unavailable() -> None:
    """Degraded path: without the index, a shape check is better than rejecting all."""
    c = WorldBankConnector()
    assert c._known_countries == set()
    assert c.normalize(_row(countryiso3code="ARB")).country_code == "ARB"


def test_validate_flags_and_rejects_non_finite() -> None:
    c = WorldBankConnector()
    good = TimeSeriesRecord(
        country_code="NGA",
        indicator_code="X",
        source_name="world_bank",
        date=dt.date(2020, 1, 1),
        value=1.0,
    )
    assert c.validate(good).is_validated is True

    nan = TimeSeriesRecord(
        country_code="NGA",
        indicator_code="X",
        source_name="world_bank",
        date=dt.date(2020, 1, 1),
        value=float("nan"),
    )
    with pytest.raises(ValidationError):
        c.validate(nan)


def test_extract_handles_no_data_payload() -> None:
    c = WorldBankConnector()
    rows, pages = c._extract([{"message": [{"id": "120", "value": "no data"}]}], "X", "u")
    assert rows == []
    assert pages == 0


async def test_fetch_paginates_and_collects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        meta = {"page": int(page), "pages": 2, "per_page": 1000, "total": 2}
        year = "2025" if page == "1" else "2024"
        return httpx.Response(200, json=[meta, [_row(date=year)]])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        c = WorldBankConnector(client=http)
        rows = await c.fetch(indicator_codes=["NY.GDP.MKTP.KD.ZG"], countries=["NGA"])

    assert len(rows) == 2
    years = {c.normalize(r).date.year for r in rows}
    assert years == {2024, 2025}


@pytest.mark.network
async def test_live_world_bank_fetch() -> None:
    """Real outbound call — run with `pytest -m network`."""
    c = WorldBankConnector()
    rows = await c.fetch(indicator_codes=["NY.GDP.MKTP.KD.ZG"], countries=["NGA"], mrv=5)
    assert rows, "expected rows from the live World Bank API"
    normalized = []
    for r in rows:
        with contextlib.suppress(NormalizationError, SkipRecord):
            normalized.append(c.normalize(r))
    assert any(rec.country_code == "NGA" for rec in normalized)
