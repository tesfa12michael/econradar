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


def test_normalize_subannual_date_rejected() -> None:
    c = WorldBankConnector()
    with pytest.raises(NormalizationError):
        c.normalize(_row(date="2025M03"))


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
