"""IMF connector — World Economic Outlook series via the IMF DataMapper API.

Keyless REST/JSON. See docs/architecture.md decision #15 for why this is *not* SDMX:
the IMF's SDMX endpoints return 501 "Data Queries are not implemented".

The response nests country series under each indicator::

    {"values": {"NGDP_RPCH": {"NGA": {"1980": 4.2, ...}, "USA": {...}, ...}}}

Two properties of WEO data drive the normalization rules:

* **Projections.** WEO publishes IMF forecasts several years past the current one.
  Storing them as history would be a groundedness violation — the dashboard would
  present a forecast as an observation. They are skipped at normalize time, so they
  never reach validation and never pollute `etl_errors`.
* **Aggregates.** The payload mixes real countries with grouping codes. A shape check
  is not enough to tell them apart — `AFR` (Africa) and `CEE` (Central and Eastern
  Europe) are three alpha characters and would sail through as countries. So the
  connector reads DataMapper's own `/countries` index and treats anything absent from
  it as an aggregate, which is *skipped* rather than rejected: publishing regional
  groupings is intended provider behaviour, not a data defect, and routing it to
  `etl_errors` would bury real failures under ~900 rows of noise per run.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from connectors.base import BaseDataSourceConnector, NormalizationError, SkipRecord
from connectors.dates import UnparseableDate, parse_period
from connectors.http import get_json
from connectors.validation import ValueKind
from logging_config import get_logger
from schemas import TimeSeriesRecord

logger = get_logger(__name__)

#: WEO indicator code -> (display name, unit, value kind). Curated to line up with the
#: World Bank set so the same concepts are comparable across sources.
IMF_INDICATORS: dict[str, tuple[str, str, ValueKind]] = {
    "NGDP_RPCH": ("Real GDP growth (annual %)", "%", ValueKind.PERCENT_CHANGE),
    "PCPIPCH": ("Inflation, average consumer prices (annual %)", "%", ValueKind.PERCENT_CHANGE),
    "NGDPDPC": ("GDP per capita, current prices (US$)", "US$", ValueKind.CURRENCY),
    "LUR": ("Unemployment rate (% of labor force)", "%", ValueKind.PERCENT_SHARE),
    "GGXWDG_NGDP": ("General government gross debt (% of GDP)", "%", ValueKind.PERCENT_SHARE),
    "BCA_NGDPD": ("Current account balance (% of GDP)", "%", ValueKind.PERCENT_SHARE),
}


class IMFConnector(BaseDataSourceConnector):
    source_name = "imf"
    base_url = "https://www.imf.org/external/datamapper/api/v1"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        client: httpx.AsyncClient | None = None,
        request_timeout: float = 60.0,
    ) -> None:
        super().__init__(session_factory=session_factory)
        self._client = client
        self._timeout = request_timeout
        #: Populated from DataMapper's /countries index during fetch(); empty until then.
        self._known_countries: set[str] = set()
        for code, (name, _unit, _kind) in IMF_INDICATORS.items():
            self._indicator_names[code] = name

    def value_kind(self, indicator_code: str) -> ValueKind | None:
        entry = IMF_INDICATORS.get(indicator_code)
        return entry[2] if entry else None

    # ── fetch ────────────────────────────────────────────────

    async def fetch(
        self,
        indicator_codes: list[str] | None = None,
        max_year: int | None = None,
        **_: Any,
    ) -> list[dict]:
        """Flatten the nested DataMapper payload into one dict per observation.

        DataMapper has no pagination — each indicator is a single response covering
        every country and year — so one request per indicator is the whole fetch.
        """
        codes = list(indicator_codes or IMF_INDICATORS)
        cutoff = max_year if max_year is not None else dt.date.today().year

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            await self._load_known_countries(client)
            rows: list[dict] = []
            for code in codes:
                payload = await get_json(client, f"{self.base_url}/{code}", source=self.source_name)
                rows.extend(self._flatten(payload, code, cutoff))
            return rows
        finally:
            if owns_client:
                await client.aclose()

    async def _load_known_countries(self, client: httpx.AsyncClient) -> None:
        """Read DataMapper's /countries index so aggregates can be told apart by name.

        On failure the set stays empty and normalize() falls back to a shape check —
        degraded, but it still refuses to invent countries.
        """
        try:
            payload = await get_json(client, f"{self.base_url}/countries", source=self.source_name)
        except Exception as exc:
            logger.warning(
                "[imf] could not load /countries index (%s); falling back to "
                "an ISO-3 shape check, which cannot detect 3-letter aggregates",
                exc,
            )
            return
        countries = (payload or {}).get("countries") or {}
        self._known_countries = {str(code).strip().upper() for code in countries}
        logger.info("[imf] loaded %d known country codes", len(self._known_countries))

    def _flatten(self, payload: Any, code: str, cutoff: int) -> list[dict]:
        """Turn {"values": {code: {area: {year: value}}}} into flat observation dicts."""
        if not isinstance(payload, dict):
            logger.warning("[imf] unexpected payload type for %s: %s", code, type(payload))
            return []
        by_area = (payload.get("values") or {}).get(code) or {}
        if not by_area:
            logger.warning("[imf] no values returned for indicator %s", code)
            return []

        rows: list[dict] = []
        for area, series in by_area.items():
            if not isinstance(series, dict):
                continue
            for year, value in series.items():
                rows.append(
                    {"area": area, "code": code, "year": year, "value": value, "cutoff": cutoff}
                )
        return rows

    # ── normalize ────────────────────────────────────────────

    def normalize(self, raw_record: dict) -> TimeSeriesRecord:
        area = str(raw_record.get("area") or "").strip().upper()
        if self._known_countries:
            if area not in self._known_countries:
                # A WEO grouping (ADVEC, AFR, WEOWORLD...). Expected output, not a defect.
                raise SkipRecord(f"aggregate/grouping area code: {area!r}")
        elif len(area) != 3 or not area.isalpha():
            # Degraded path: the /countries index was unavailable.
            raise NormalizationError(f"non-ISO-3 area code: {area!r}")

        code = raw_record.get("code")
        if not code:
            raise NormalizationError("missing indicator code")

        value = raw_record.get("value")
        if value is None:
            raise SkipRecord(f"no observation for {area}/{code}/{raw_record.get('year')}")

        try:
            obs_date, frequency = parse_period(raw_record.get("year"))
        except UnparseableDate as exc:
            raise NormalizationError(str(exc)) from exc

        # WEO forecasts are not observations. Skipping (rather than rejecting) keeps
        # etl_errors meaningful: a projection is expected output, not a data defect.
        cutoff = raw_record.get("cutoff")
        if isinstance(cutoff, int) and obs_date.year > cutoff:
            raise SkipRecord(f"IMF projection for {area}/{code}/{obs_date.year} (> {cutoff})")

        _name, unit, _kind = IMF_INDICATORS.get(code, (code, None, None))
        try:
            return TimeSeriesRecord(
                country_code=area,
                indicator_code=code,
                source_name=self.source_name,
                date=obs_date,
                value=float(value),
                unit=unit,
                frequency=frequency,
            )
        except (PydanticValidationError, TypeError, ValueError) as exc:
            raise NormalizationError(f"could not build record: {exc}") from exc


def imf_focus_indicators() -> list[str]:
    """Indicator codes the scheduled IMF refresh ingests."""
    return list(settings.imf_indicators or IMF_INDICATORS)
