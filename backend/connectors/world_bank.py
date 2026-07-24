"""World Bank connector — the first concrete BaseDataSourceConnector.

Keyless REST/JSON. The World Bank v2 API returns ``[metadata, [rows]]``; each row
looks like::

    {"countryiso3code": "NGA", "indicator": {"id": "...", "value": "..."},
     "date": "2025", "value": 4.01, "unit": ""}

`value` is ``null`` for years with no observation (skipped, not an error), and rows
for aggregates/regions carry a non-ISO-3 code (rejected to etl_errors). Only annual
dates are handled in Phase 1; monthly ("2025M03") / quarterly ("2025Q1") parsing is
deferred to Phase 2.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

import httpx
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from connectors.base import BaseDataSourceConnector, NormalizationError, SkipRecord
from logging_config import get_logger
from schemas import TimeSeriesRecord

logger = get_logger(__name__)

_RETRYABLE_ATTEMPTS = 4
_INITIAL_BACKOFF_S = 0.5


class WorldBankAPIError(Exception):
    """The World Bank API was unreachable or returned a retryable error repeatedly."""


class WorldBankConnector(BaseDataSourceConnector):
    source_name = "world_bank"
    base_url = "https://api.worldbank.org/v2"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        client: httpx.AsyncClient | None = None,
        per_page: int = 1000,
        request_timeout: float = 30.0,
    ) -> None:
        super().__init__(session_factory=session_factory)
        self._client = client
        self._per_page = per_page
        self._timeout = request_timeout

    # ── fetch ────────────────────────────────────────────────

    async def fetch(
        self,
        indicator_codes: list[str] | None = None,
        countries: list[str] | str | None = None,
        mrv: int | None = None,
        start_year: int | None = None,
        end_year: int | None = None,
        **_: Any,
    ) -> list[dict]:
        """Fetch rows for each indicator across the given countries (de-paginated)."""
        indicator_codes = list(indicator_codes or settings.world_bank_indicators)
        countries_param = self._countries_param(countries)

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            rows: list[dict] = []
            for code in indicator_codes:
                rows.extend(
                    await self._fetch_indicator(
                        client, countries_param, code, mrv, start_year, end_year
                    )
                )
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

    async def _fetch_indicator(
        self,
        client: httpx.AsyncClient,
        countries_param: str,
        code: str,
        mrv: int | None,
        start_year: int | None,
        end_year: int | None,
    ) -> list[dict]:
        params: dict[str, Any] = {"format": "json", "per_page": self._per_page, "page": 1}
        if mrv is not None:
            params["mrv"] = mrv
        elif start_year is not None and end_year is not None:
            params["date"] = f"{start_year}:{end_year}"
        url = f"{self.base_url}/country/{countries_param}/indicator/{code}"

        first = await self._get_json(client, url, params)
        rows, pages = self._extract(first, code, url)
        for page in range(2, pages + 1):
            payload = await self._get_json(client, url, {**params, "page": page})
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

    async def _get_json(self, client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> Any:
        """GET with exponential backoff on transport errors, 429s, and 5xx."""
        delay = _INITIAL_BACKOFF_S
        last_error: Exception | None = None
        for attempt in range(1, _RETRYABLE_ATTEMPTS + 1):
            try:
                resp = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_error = WorldBankAPIError(f"HTTP {resp.status_code} for {resp.url}")
                else:
                    resp.raise_for_status()
                    return resp.json()
            if attempt < _RETRYABLE_ATTEMPTS:
                logger.warning(
                    "[world_bank] retry %d/%d after error: %s",
                    attempt,
                    _RETRYABLE_ATTEMPTS,
                    last_error,
                )
                await asyncio.sleep(delay)
                delay *= 2
        raise WorldBankAPIError(f"World Bank request failed after retries: {url}") from last_error

    # ── normalize ────────────────────────────────────────────

    def normalize(self, raw_record: dict) -> TimeSeriesRecord:
        iso3 = (raw_record.get("countryiso3code") or "").strip()
        if len(iso3) != 3 or not iso3.isalpha():
            # Aggregate / regional rows (e.g. "Sub-Saharan Africa") have no ISO-3 code.
            raise NormalizationError(f"non-ISO-3 country code: {iso3!r}")

        indicator = raw_record.get("indicator") or {}
        code = indicator.get("id")
        if not code:
            raise NormalizationError("missing indicator id")
        if indicator.get("value"):
            self._indicator_names[code] = indicator["value"]

        value = raw_record.get("value")
        if value is None:
            raise SkipRecord(f"null value for {iso3}/{code}/{raw_record.get('date')}")

        obs_date = self._parse_date(raw_record.get("date"))
        try:
            return TimeSeriesRecord(
                country_code=iso3,
                indicator_code=code,
                source_name=self.source_name,
                date=obs_date,
                value=float(value),
                unit=(raw_record.get("unit") or None),
            )
        except (PydanticValidationError, TypeError, ValueError) as exc:
            raise NormalizationError(f"could not build record: {exc}") from exc

    @staticmethod
    def _parse_date(raw_date: Any) -> dt.date:
        s = str(raw_date or "").strip()
        if len(s) == 4 and s.isdigit():
            return dt.date(int(s), 1, 1)  # annual -> Jan 1
        if "M" in s or "Q" in s:
            raise NormalizationError(f"sub-annual frequency not supported in Phase 1: {s!r}")
        raise NormalizationError(f"unparseable date: {s!r}")
