"""Feature 1.1 — IMF, BIS, FRED and WB DataBank connectors.

Fixture-driven so CI stays hermetic; the live-API checks are marked `network` and
deselected by default. Each connector is exercised through the same contract:
fetch shape -> normalize -> the accept/reject/skip partition.
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from connectors import (
    BISConnector,
    FREDConnector,
    IMFConnector,
    NormalizationError,
    SkipRecord,
    WBDataBankConnector,
)
from connectors.bis import POLICY_RATE_CODE

# ── IMF ──────────────────────────────────────────────────────

_IMF_PAYLOAD = {
    "values": {
        "NGDP_RPCH": {
            "NGA": {"2020": -1.8, "2021": 3.6, "2030": 5.0},
            "AFR": {"2020": 1.1},  # a 3-letter *aggregate*, not a country
            "WEOWORLD": {"2020": -2.7},
        }
    }
}


def _imf(known: set[str] | None = None) -> IMFConnector:
    c = IMFConnector()
    if known is not None:
        c._known_countries = known
    return c


def test_imf_flattens_nested_payload() -> None:
    rows = _imf()._flatten(_IMF_PAYLOAD, "NGDP_RPCH", cutoff=2026)
    assert len(rows) == 5
    assert {r["area"] for r in rows} == {"NGA", "AFR", "WEOWORLD"}


def test_imf_three_letter_aggregate_is_skipped_not_stored() -> None:
    """AFR passes an ISO-3 shape check, so only the /countries index catches it."""
    c = _imf(known={"NGA"})
    with pytest.raises(SkipRecord):
        c.normalize({"area": "AFR", "code": "NGDP_RPCH", "year": "2020", "value": 1.1})


def test_imf_projections_are_skipped_not_rejected() -> None:
    """A forecast is expected provider output; it must not pollute etl_errors."""
    c = _imf(known={"NGA"})
    with pytest.raises(SkipRecord):
        c.normalize(
            {"area": "NGA", "code": "NGDP_RPCH", "year": "2030", "value": 5.0, "cutoff": 2026}
        )


def test_imf_accepts_a_real_observation() -> None:
    c = _imf(known={"NGA"})
    rec = c.normalize(
        {"area": "NGA", "code": "NGDP_RPCH", "year": "2021", "value": 3.6, "cutoff": 2026}
    )
    assert rec.country_code == "NGA"
    assert rec.date == dt.date(2021, 1, 1)
    assert rec.frequency == "annual"
    assert rec.unit == "%"


def test_imf_process_partitions_a_batch() -> None:
    c = _imf(known={"NGA"})
    rows = c._flatten(_IMF_PAYLOAD, "NGDP_RPCH", cutoff=2026)
    good, rejected, skipped = c.process(rows)
    assert [r.date.year for r in good] == [2020, 2021]
    assert rejected == []  # aggregates and projections are skips, not errors
    assert skipped == 3


async def test_imf_fetch_loads_country_index() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/countries"):
            return httpx.Response(200, json={"countries": {"NGA": {"label": "Nigeria"}}})
        return httpx.Response(200, json=_IMF_PAYLOAD)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        c = IMFConnector(client=http)
        rows = await c.fetch(indicator_codes=["NGDP_RPCH"], max_year=2026)
        assert c._known_countries == {"NGA"}
    good, _, _ = c.process(rows)
    assert {r.country_code for r in good} == {"NGA"}


# ── BIS ──────────────────────────────────────────────────────

#: Mirrors the real feed: quoted COMPILATION notes containing commas AND a newline.
_BIS_CSV = (
    "FREQ,REF_AREA,UNIT_MEASURE,COMPILATION,TIME_PERIOD,OBS_VALUE\n"
    'M,US,368,"From 19 Dec 1985 onwards: mid-point of the target rate,\n'
    'earlier the effective rate.",2026-06,3.625\n'
    "M,GB,368,simple note,2026-06,3.75\n"
    "M,XM,368,euro area aggregate,2026-06,2.0\n"
    "M,ZA,368,,2026-06,NaN\n"
)


def test_bis_csv_survives_embedded_commas_and_newlines() -> None:
    """Splitting on commas would corrupt these rows; DictReader must not."""
    rows = BISConnector.parse_csv(_BIS_CSV)
    assert len(rows) == 4
    assert [r["REF_AREA"] for r in rows] == ["US", "GB", "XM", "ZA"]
    assert rows[0]["OBS_VALUE"] == "3.625"
    assert "\n" in rows[0]["COMPILATION"]


def test_bis_converts_iso2_to_iso3() -> None:
    rec = BISConnector().normalize(
        {"REF_AREA": "US", "TIME_PERIOD": "2026-06", "OBS_VALUE": "3.625"}
    )
    assert rec.country_code == "USA"
    assert rec.indicator_code == POLICY_RATE_CODE
    assert rec.date == dt.date(2026, 6, 1)
    assert rec.frequency == "monthly"


def test_bis_euro_area_is_skipped() -> None:
    with pytest.raises(SkipRecord):
        BISConnector().normalize({"REF_AREA": "XM", "TIME_PERIOD": "2026-06", "OBS_VALUE": "2.0"})


def test_bis_nan_sentinel_is_skipped_not_rejected() -> None:
    with pytest.raises(SkipRecord):
        BISConnector().normalize({"REF_AREA": "ZA", "TIME_PERIOD": "2026-06", "OBS_VALUE": "NaN"})


def test_bis_unmapped_country_code_is_rejected_loudly() -> None:
    with pytest.raises(NormalizationError):
        BISConnector().normalize({"REF_AREA": "QQ", "TIME_PERIOD": "2026-06", "OBS_VALUE": "1.0"})


def test_bis_full_batch_partition() -> None:
    good, rejected, skipped = BISConnector().process(BISConnector.parse_csv(_BIS_CSV))
    assert {r.country_code for r in good} == {"USA", "GBR"}
    assert rejected == []
    assert skipped == 2  # euro-area aggregate + NaN gap


def test_bis_xml_error_document_is_not_parsed_as_csv() -> None:
    assert BISConnector.parse_csv('<?xml version="1.0"?><Error/>') == []


# ── FRED ─────────────────────────────────────────────────────


async def test_fred_self_disables_without_a_key() -> None:
    """A missing optional key degrades one source; it must not raise."""
    c = FREDConnector(api_key=None)
    assert c.is_configured is False
    assert await c.fetch() == []


async def test_unconfigured_source_records_no_pipeline_run() -> None:
    """A source that never ran must not claim a last_successful_run on /status.

    run() short-circuits before touching the database, so no session factory is
    needed — which is also what proves nothing was written.
    """
    result = await FREDConnector(api_key=None).run()
    assert result.status == "skipped"
    assert result.run_id is None
    assert result.records_inserted == 0


def test_fred_maps_series_id_to_country_and_indicator() -> None:
    c = FREDConnector(api_key="test")
    rec = c.normalize({"series_id": "FEDFUNDS", "date": "2026-06-01", "value": "4.33"})
    assert rec.country_code == "USA"
    assert rec.indicator_code == "FRED.POLRATE"
    assert rec.date == dt.date(2026, 6, 1)


def test_fred_missing_observation_sentinel_is_skipped() -> None:
    c = FREDConnector(api_key="test")
    with pytest.raises(SkipRecord):
        c.normalize({"series_id": "FEDFUNDS", "date": "2026-06-01", "value": "."})


def test_fred_unregistered_series_is_rejected() -> None:
    c = FREDConnector(api_key="test")
    with pytest.raises(NormalizationError):
        c.normalize({"series_id": "MADE_UP", "date": "2026-06-01", "value": "1.0"})


async def test_fred_fetch_tags_rows_with_their_series_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"observations": [{"date": "2026-06-01", "value": "4.33"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        c = FREDConnector(client=http, api_key="test")
        rows = await c.fetch(series_ids=["FEDFUNDS"])
    assert rows == [{"date": "2026-06-01", "value": "4.33", "series_id": "FEDFUNDS"}]
    good, _, _ = c.process(rows)
    assert good[0].country_code == "USA"


# ── WB DataBank ──────────────────────────────────────────────


def test_databank_uses_the_gem_source_parameter() -> None:
    assert WBDataBankConnector()._extra_params() == {"source": 15}


def test_databank_reads_iso3_from_country_id() -> None:
    """source=15 leaves countryiso3code empty — the WDI shape is inverted here."""
    rec = WBDataBankConnector().normalize(
        {
            "indicator": {"id": "DPANUSSPB", "value": "Exchange rate"},
            "country": {"id": "NGA", "value": "Nigeria"},
            "countryiso3code": "",
            "date": "2025M06",
            "value": 1552.2,
        }
    )
    assert rec.country_code == "NGA"
    assert rec.date == dt.date(2025, 6, 1)
    assert rec.frequency == "monthly"
    assert rec.unit == "LCU/US$"


def test_databank_is_a_distinct_source_from_world_bank() -> None:
    assert WBDataBankConnector.source_name == "wb_databank"


# ── live API checks (deselected by default) ──────────────────


@pytest.mark.network
async def test_live_imf_fetch() -> None:
    c = IMFConnector()
    rows = await c.fetch(indicator_codes=["NGDP_RPCH"])
    good, rejected, _ = c.process(rows)
    assert good, "expected observations from the live IMF DataMapper API"
    assert rejected == [], "live IMF fetch should produce no ETL errors"
    assert any(r.country_code == "NGA" for r in good)


@pytest.mark.network
async def test_live_bis_fetch() -> None:
    c = BISConnector()
    rows = await c.fetch(last_n_observations=3)
    good, rejected, _ = c.process(rows)
    assert good, "expected observations from the live BIS API"
    assert rejected == [], "live BIS fetch should produce no ETL errors"
    assert any(r.country_code == "USA" for r in good)


@pytest.mark.network
async def test_live_databank_fetch() -> None:
    c = WBDataBankConnector()
    rows = await c.fetch(countries=["NGA"], start_period="2025M01", end_period="2025M06")
    good, rejected, _ = c.process(rows)
    assert good, "expected monthly observations from the live GEM source"
    assert rejected == []
    assert all(r.frequency == "monthly" for r in good)
