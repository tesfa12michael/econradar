"""World Bank connector — the first concrete BaseDataSourceConnector.

Keyless REST/JSON. The World Bank v2 API returns ``[metadata, [rows]]``; each row
looks like::

    {"countryiso3code": "NGA", "indicator": {"id": "...", "value": "..."},
     "date": "2025", "value": 4.01, "unit": ""}

`value` is ``null`` for years with no observation, which is skipped rather than treated
as an error. Annual, monthly ("2025M03") and quarterly ("2025Q1") periods all parse via
connectors/dates.py.

The API mixes regional and income-group aggregates in with real countries, in two
different shapes — three-letter groupings (ARB, EMU, WLD) and two-letter income groups
(XD, XM, XT). Neither can be filtered by code shape alone, so the connector consults the
API's own `/country` index, where aggregates are marked `region.id == "NA"`.

Subclassed by WBDataBankConnector, which points the same machinery at `?source=15`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from connectors.base import BaseDataSourceConnector, NormalizationError, SkipRecord
from connectors.dates import UnparseableDate, parse_period
from connectors.http import SourceAPIError, get_json
from connectors.validation import ValueKind
from logging_config import get_logger
from schemas import TimeSeriesRecord

logger = get_logger(__name__)

#: Retained as an alias so existing imports keep working after retry/backoff moved
#: into the shared connectors/http.py used by all five sources.
WorldBankAPIError = SourceAPIError

#: Pause between paged requests. See _fetch_indicator for why this exists.
_PAGE_SPACING_S = 0.35

#: The World Bank leaves `unit` blank on essentially every WDI row, so units for the
#: curated indicator set are declared here and mirror supabase/seeds/0004.
_UNITS: dict[str, str] = {
    "NY.GDP.MKTP.KD.ZG": "%",
    "FP.CPI.TOTL.ZG": "%",
    "NY.GDP.PCAP.CD": "US$",
    "SL.UEM.TOTL.ZS": "%",
    "NE.EXP.GNFS.ZS": "%",
    "NE.IMP.GNFS.ZS": "%",
    "GC.DOD.TOTL.GD.ZS": "%",
    "BN.CAB.XOKA.GD.ZS": "%",
}

#: Semantics for plausibility bounds (connectors/validation.py). Only the indicators
#: whose units we actually know are listed; anything else is bound-free by design.
_VALUE_KINDS: dict[str, ValueKind] = {
    "NY.GDP.MKTP.KD.ZG": ValueKind.PERCENT_CHANGE,
    "FP.CPI.TOTL.ZG": ValueKind.PERCENT_CHANGE,
    "NY.GDP.PCAP.CD": ValueKind.CURRENCY,
    "SL.UEM.TOTL.ZS": ValueKind.PERCENT_SHARE,
    "NE.EXP.GNFS.ZS": ValueKind.PERCENT_SHARE,
    "NE.IMP.GNFS.ZS": ValueKind.PERCENT_SHARE,
    "GC.DOD.TOTL.GD.ZS": ValueKind.PERCENT_SHARE,
    "BN.CAB.XOKA.GD.ZS": ValueKind.PERCENT_SHARE,
}


class WorldBankConnector(BaseDataSourceConnector):
    source_name = "world_bank"
    base_url = "https://api.worldbank.org/v2"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        client: httpx.AsyncClient | None = None,
        # Large pages are the main defence against World Bank throttling: at "all
        # countries" scope this turns ~18 paged requests per indicator into one.
        per_page: int = 20000,
        request_timeout: float = 30.0,
    ) -> None:
        super().__init__(session_factory=session_factory)
        self._client = client
        self._per_page = per_page
        self._timeout = request_timeout
        #: Real countries, loaded from the /country index during fetch(). Empty until then.
        self._known_countries: set[str] = set()

    def value_kind(self, indicator_code: str) -> ValueKind | None:
        return _VALUE_KINDS.get(indicator_code)

    async def _load_known_countries(self, client: httpx.AsyncClient) -> None:
        """Load the real-country list so regional aggregates can be excluded.

        A shape check is not sufficient: World Bank aggregates such as ARB (Arab World),
        EMU (Euro area) and WLD (World) carry perfectly well-formed three-letter codes
        and would otherwise be stored as if they were countries, quietly skewing every
        world average on the dashboard. The API marks aggregates with region.id == "NA".
        """
        try:
            payload = await get_json(
                client,
                f"{self.base_url}/country",
                source=self.source_name,
                params={"format": "json", "per_page": 400},
            )
            rows = payload[1] if isinstance(payload, list) and len(payload) == 2 else []
        except Exception as exc:
            logger.warning(
                "[%s] could not load the /country index (%s); falling back to a shape "
                "check, which cannot exclude 3-letter aggregates",
                self.source_name,
                exc,
            )
            return

        self._known_countries = {
            str(row.get("id") or "").strip().upper()
            for row in rows
            if (row.get("region") or {}).get("id") != "NA"
        }
        logger.info(
            "[%s] loaded %d real country codes (aggregates excluded)",
            self.source_name,
            len(self._known_countries),
        )

    # ── fetch ────────────────────────────────────────────────

    async def fetch(
        self,
        indicator_codes: list[str] | None = None,
        countries: list[str] | str | None = None,
        mrv: int | None = None,
        start_year: int | None = None,
        end_year: int | None = None,
        date_range: str | None = None,
        **_: Any,
    ) -> list[dict]:
        """Fetch rows for each indicator across the given countries (de-paginated)."""
        indicator_codes = list(indicator_codes or settings.world_bank_indicators)
        countries_param = self._countries_param(countries)
        if date_range is None and start_year is not None and end_year is not None:
            date_range = f"{start_year}:{end_year}"

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            await self._load_known_countries(client)
            rows: list[dict] = []
            failures = 0
            for code in indicator_codes:
                try:
                    rows.extend(
                        await self._fetch_indicator(client, countries_param, code, mrv, date_range)
                    )
                except (httpx.HTTPError, SourceAPIError) as exc:
                    # One indicator failing must not discard the others already fetched.
                    failures += 1
                    self.record_fetch_error(f"indicator {code}", exc)
            if failures and failures == len(indicator_codes):
                raise SourceAPIError(f"all {failures} {self.source_name} indicator requests failed")
            return rows
        finally:
            if owns_client:
                await client.aclose()

    def _countries_param(self, countries: list[str] | str | None) -> str:
        if countries is None:
            countries = list(settings.focus_countries)
        if isinstance(countries, str):
            return countries  # e.g. "all" or a single code
        return ";".join(countries)  # World Bank multi-country syntax

    def _extra_params(self) -> dict[str, Any]:
        """Extra query params for this surface. Subclasses add `source=N` (DataBank)."""
        return {}

    async def _fetch_indicator(
        self,
        client: httpx.AsyncClient,
        countries_param: str,
        code: str,
        mrv: int | None,
        date_range: str | None,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "format": "json",
            "per_page": self._per_page,
            "page": 1,
            **self._extra_params(),
        }
        if mrv is not None:
            params["mrv"] = mrv
        elif date_range is not None:
            params["date"] = date_range
        url = f"{self.base_url}/country/{countries_param}/indicator/{code}"

        first = await get_json(client, url, source=self.source_name, params=params)
        rows, pages = self._extract(first, code, url)
        for page in range(2, pages + 1):
            # The World Bank signals throttling with HTTP 400, not 429, so backoff
            # cannot recognise it as retryable. Pacing the requests avoids tripping it
            # in the first place, which matters at "all countries" scope.
            await asyncio.sleep(_PAGE_SPACING_S)
            payload = await get_json(
                client, url, source=self.source_name, params={**params, "page": page}
            )
            page_rows, _ = self._extract(payload, code, url)
            rows.extend(page_rows)
        return rows

    def _extract(self, payload: Any, code: str, url: str) -> tuple[list[dict], int]:
        """Pull the row list + page count from a World Bank ``[meta, data]`` payload."""
        if not (isinstance(payload, list) and len(payload) == 2 and isinstance(payload[1], list)):
            # WB returns [{"message": [...]}] for unknown indicators / no data.
            logger.warning("[world_bank] no data for %s (%s)", code, url)
            return [], 0
        meta, data = payload
        # Capture the display name for catalog upsert.
        if data:
            self._indicator_names[code] = data[0].get("indicator", {}).get("value", code)
        pages = int(meta.get("pages", 1) or 1)
        return data, pages

    # ── normalize ────────────────────────────────────────────

    def normalize(self, raw_record: dict) -> TimeSeriesRecord:
        iso3 = self._resolve_country(raw_record)

        indicator = raw_record.get("indicator") or {}
        code = indicator.get("id")
        if not code:
            raise NormalizationError("missing indicator id")
        if indicator.get("value"):
            self._indicator_names[code] = indicator["value"]

        value = raw_record.get("value")
        if value is None:
            raise SkipRecord(f"null value for {iso3}/{code}/{raw_record.get('date')}")

        try:
            obs_date, frequency = parse_period(raw_record.get("date"))
        except UnparseableDate as exc:
            raise NormalizationError(str(exc)) from exc

        try:
            return TimeSeriesRecord(
                country_code=iso3,
                indicator_code=code,
                source_name=self.source_name,
                date=obs_date,
                value=float(value),
                unit=(raw_record.get("unit") or None) or _UNITS.get(code),
                frequency=frequency,
            )
        except (PydanticValidationError, TypeError, ValueError) as exc:
            raise NormalizationError(f"could not build record: {exc}") from exc

    @staticmethod
    def _raw_country_code(raw_record: dict) -> str:
        """The record's country code, tolerating two different response shapes.

        On the WDI surface (`source=2`) `countryiso3code` is populated. On some other
        DataBank sources (notably `source=15`) it is an empty string and `country.id`
        carries the ISO-3 code instead — so fall back rather than reject a good row.
        """
        iso3 = (raw_record.get("countryiso3code") or "").strip().upper()
        if len(iso3) != 3 or not iso3.isalpha():
            iso3 = str((raw_record.get("country") or {}).get("id") or "").strip().upper()
        return iso3

    def _resolve_country(self, raw_record: dict) -> str:
        """Resolve to a real ISO-3 country, skipping the aggregates the API mixes in.

        World Bank aggregates come in two shapes and both must be *skipped* rather
        than logged as errors, since publishing them is intended behaviour:
          * three-letter groupings — ARB, EMU, WLD, SSF;
          * two-letter income groups — XD (high income), XM, XN, XT, XY.
        Checking membership of the real-country index handles both uniformly.
        """
        code = self._raw_country_code(raw_record)
        if not code:
            raise NormalizationError("missing country code")
        if self._known_countries:
            if code not in self._known_countries:
                raise SkipRecord(f"aggregate/grouping code: {code!r}")
            return code
        # Degraded path: no index available, so fall back to a shape check.
        if len(code) != 3 or not code.isalpha():
            raise NormalizationError(f"non-ISO-3 country code: {code!r}")
        return code
