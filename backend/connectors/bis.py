"""BIS connector — central bank policy rates via the BIS SDMX 2.1 REST API.

Served as **CSV**, not JSON: BIS rejects `format=jsondata` with HTTP 406, and the CSV
surface is a flat row per observation rather than SDMX-JSON's dimension-index encoding
(docs/architecture.md decision #16).

Two things make this CSV hostile to naive parsing, and both are load-bearing:

* The `COMPILATION` column carries free-text methodology notes containing **commas and
  embedded newlines** inside quoted fields. Splitting on commas silently corrupts rows,
  so this module uses `csv.DictReader`, which handles RFC 4180 quoting correctly.
* `REF_AREA` is **ISO-2**, so codes are converted via connectors/countries.py. The euro
  area (`XM`) is published alongside its member states and is skipped as an aggregate.
"""

from __future__ import annotations

import csv
import io
from typing import Any

import httpx
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from connectors.base import BaseDataSourceConnector, NormalizationError, SkipRecord
from connectors.countries import UnknownCountryCode, is_aggregate, to_alpha3
from connectors.dates import UnparseableDate, parse_period
from connectors.http import get_text
from connectors.validation import ValueKind
from logging_config import get_logger
from schemas import TimeSeriesRecord

logger = get_logger(__name__)

#: The BIS dataflow this connector ingests, as agency/flow/version path segments.
#: Policy rates are the BIS series with the broadest country coverage (49 reporting
#: areas) and the clearest dashboard value.
POLICY_RATE_FLOW = "BIS/WS_CBPOL/1.0"
POLICY_RATE_CODE = "CBPOL"
POLICY_RATE_NAME = "Central bank policy rate (%)"


class BISConnector(BaseDataSourceConnector):
    source_name = "bis"
    base_url = "https://stats.bis.org/api/v2"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        client: httpx.AsyncClient | None = None,
        request_timeout: float = 90.0,
    ) -> None:
        super().__init__(session_factory=session_factory)
        self._client = client
        self._timeout = request_timeout
        self._indicator_names[POLICY_RATE_CODE] = POLICY_RATE_NAME

    def value_kind(self, indicator_code: str) -> ValueKind | None:
        return ValueKind.RATE if indicator_code == POLICY_RATE_CODE else None

    # ── fetch ────────────────────────────────────────────────

    async def fetch(
        self,
        frequency: str = "M",
        last_n_observations: int | None = None,
        start_period: str | None = None,
        **_: Any,
    ) -> list[dict]:
        """Fetch policy rates for every reporting area.

        The series key is frequency alone (`M`), which BIS reads as "all reference
        areas" — one request covers every central bank rather than one per country.
        """
        params: dict[str, Any] = {"format": "csv"}
        if last_n_observations is not None:
            params["lastNObservations"] = last_n_observations
        elif start_period is not None:
            params["startPeriod"] = start_period

        url = f"{self.base_url}/data/dataflow/{POLICY_RATE_FLOW}/{frequency}"

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            body = await get_text(client, url, source=self.source_name, params=params)
        finally:
            if owns_client:
                await client.aclose()
        return self.parse_csv(body)

    @staticmethod
    def parse_csv(body: str) -> list[dict]:
        """Parse the SDMX CSV body into raw observation dicts.

        Uses csv.DictReader rather than string splitting because the COMPILATION column
        contains commas and newlines inside quoted fields.
        """
        text = body.lstrip("﻿")
        if not text.strip():
            return []
        if text.lstrip().startswith("<"):
            # BIS reports "no results for query" as an SDMX XML error document.
            logger.warning("[bis] non-CSV response: %s", text.strip()[:200])
            return []
        return [dict(row) for row in csv.DictReader(io.StringIO(text))]

    # ── normalize ────────────────────────────────────────────

    def normalize(self, raw_record: dict) -> TimeSeriesRecord:
        area = str(raw_record.get("REF_AREA") or "").strip().upper()
        if not area:
            raise NormalizationError("missing REF_AREA")
        if is_aggregate(area):
            raise SkipRecord(f"aggregate reference area: {area}")
        try:
            iso3 = to_alpha3(area)
        except UnknownCountryCode as exc:
            raise NormalizationError(str(exc)) from exc

        raw_value = str(raw_record.get("OBS_VALUE") or "").strip()
        # BIS writes a literal "NaN" for a period with no rate (a gap in an otherwise
        # live series), which is a missing-value sentinel rather than corrupt data.
        if not raw_value or raw_value.lower() == "nan":
            raise SkipRecord(f"no observation for {iso3}/{raw_record.get('TIME_PERIOD')}")

        try:
            obs_date, frequency = parse_period(raw_record.get("TIME_PERIOD"))
        except UnparseableDate as exc:
            raise NormalizationError(str(exc)) from exc

        try:
            return TimeSeriesRecord(
                country_code=iso3,
                indicator_code=POLICY_RATE_CODE,
                source_name=self.source_name,
                date=obs_date,
                value=float(raw_value),
                unit="%",
                frequency=frequency,
            )
        except (PydanticValidationError, TypeError, ValueError) as exc:
            raise NormalizationError(f"could not build record: {exc}") from exc
