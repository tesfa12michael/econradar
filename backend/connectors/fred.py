"""FRED connector — St. Louis Fed economic series.

The only keyed source in the set: keyless requests return HTTP 400 ("Variable api_key
is not set"). Without `FRED_API_KEY` configured the connector **self-disables** — it
logs once and returns no rows, rather than raising — so a missing optional key degrades
one source instead of failing a scheduled run.

FRED is series-oriented, not country-oriented: a series id encodes its own country and
concept with no parseable structure (`CPALTT01USM657N` is US CPI). So the country and
indicator mapping is an explicit curated registry rather than anything derived, and
adding coverage means adding a registry entry.

Discontinued series are a documented edge case: FRED keeps them queryable and simply
stops emitting new observations, so a stale series is not an error. Genuinely missing
observations arrive as the string "." and are skipped.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
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

#: FRED's documented ceiling is 120 requests/minute; the registry is far smaller than
#: that, but the pause keeps burst behaviour polite if the registry grows.
_REQUEST_SPACING_S = 0.2


@dataclass(frozen=True, slots=True)
class FredSeries:
    series_id: str
    country_code: str  # ISO-3
    indicator_code: str  # EconRadar-side code, shared across countries
    indicator_name: str
    unit: str
    kind: ValueKind


#: Curated series. Indicator codes are EconRadar-side so the same concept lines up
#: across countries, while series_id stays FRED's own identifier.
FRED_SERIES: tuple[FredSeries, ...] = (
    FredSeries("FEDFUNDS", "USA", "FRED.POLRATE", "Policy interest rate (%)", "%", ValueKind.RATE),
    FredSeries(
        "UNRATE", "USA", "FRED.UNRATE", "Unemployment rate (%)", "%", ValueKind.PERCENT_SHARE
    ),
    FredSeries(
        "CPIAUCSL",
        "USA",
        "FRED.CPI",
        "Consumer price index (1982-84=100)",
        "index",
        ValueKind.INDEX,
    ),
    FredSeries(
        "DGS10", "USA", "FRED.GOV10Y", "10-year government bond yield (%)", "%", ValueKind.RATE
    ),
    FredSeries(
        "IRLTLT01DEM156N",
        "DEU",
        "FRED.GOV10Y",
        "10-year government bond yield (%)",
        "%",
        ValueKind.RATE,
    ),
    FredSeries(
        "IRLTLT01GBM156N",
        "GBR",
        "FRED.GOV10Y",
        "10-year government bond yield (%)",
        "%",
        ValueKind.RATE,
    ),
    FredSeries(
        "IRLTLT01JPM156N",
        "JPN",
        "FRED.GOV10Y",
        "10-year government bond yield (%)",
        "%",
        ValueKind.RATE,
    ),
    FredSeries(
        "LRHUTTTTDEM156S",
        "DEU",
        "FRED.UNRATE",
        "Unemployment rate (%)",
        "%",
        ValueKind.PERCENT_SHARE,
    ),
    FredSeries(
        "LRHUTTTTJPM156S",
        "JPN",
        "FRED.UNRATE",
        "Unemployment rate (%)",
        "%",
        ValueKind.PERCENT_SHARE,
    ),
)

_BY_SERIES_ID: dict[str, FredSeries] = {s.series_id: s for s in FRED_SERIES}
_KINDS: dict[str, ValueKind] = {s.indicator_code: s.kind for s in FRED_SERIES}


class FREDConnector(BaseDataSourceConnector):
    source_name = "fred"
    base_url = "https://api.stlouisfed.org/fred"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        client: httpx.AsyncClient | None = None,
        api_key: str | None = None,
        request_timeout: float = 45.0,
    ) -> None:
        super().__init__(session_factory=session_factory)
        self._client = client
        self._api_key = api_key if api_key is not None else settings.fred_api_key
        self._timeout = request_timeout
        for series in FRED_SERIES:
            self._indicator_names[series.indicator_code] = series.indicator_name

    @property
    def is_configured(self) -> bool:
        """False without an API key, which makes run() skip without recording a run."""
        return bool(self._api_key)

    def value_kind(self, indicator_code: str) -> ValueKind | None:
        return _KINDS.get(indicator_code)

    # ── fetch ────────────────────────────────────────────────

    async def fetch(
        self,
        series_ids: list[str] | None = None,
        observation_start: str | None = None,
        **_: Any,
    ) -> list[dict]:
        if not self.is_configured:
            logger.warning(
                "[fred] FRED_API_KEY is not set — skipping ingestion. "
                "The connector is wired and will start working as soon as a key is present."
            )
            return []

        wanted = [_BY_SERIES_ID[s] for s in series_ids] if series_ids else list(FRED_SERIES)

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            rows: list[dict] = []
            for index, series in enumerate(wanted):
                if index:
                    await asyncio.sleep(_REQUEST_SPACING_S)  # stay well under 120 req/min
                rows.extend(await self._fetch_series(client, series, observation_start))
            return rows
        finally:
            if owns_client:
                await client.aclose()

    async def _fetch_series(
        self, client: httpx.AsyncClient, series: FredSeries, observation_start: str | None
    ) -> list[dict]:
        params: dict[str, Any] = {
            "series_id": series.series_id,
            "api_key": self._api_key,
            "file_type": "json",
        }
        if observation_start:
            params["observation_start"] = observation_start

        payload = await get_json(
            client, f"{self.base_url}/series/observations", source=self.source_name, params=params
        )
        observations = (payload or {}).get("observations") or []
        if not observations:
            # A discontinued series still resolves; it just stops emitting rows.
            logger.info("[fred] no observations returned for %s", series.series_id)
        return [{**obs, "series_id": series.series_id} for obs in observations]

    # ── normalize ────────────────────────────────────────────

    def normalize(self, raw_record: dict) -> TimeSeriesRecord:
        series_id = str(raw_record.get("series_id") or "").strip()
        series = _BY_SERIES_ID.get(series_id)
        if series is None:
            raise NormalizationError(f"unregistered FRED series id: {series_id!r}")

        raw_value = str(raw_record.get("value") or "").strip()
        if not raw_value or raw_value == ".":
            # FRED's documented sentinel for a gap in an otherwise live series.
            raise SkipRecord(f"missing observation for {series_id}/{raw_record.get('date')}")

        try:
            obs_date, frequency = parse_period(raw_record.get("date"))
        except UnparseableDate as exc:
            raise NormalizationError(str(exc)) from exc

        try:
            return TimeSeriesRecord(
                country_code=series.country_code,
                indicator_code=series.indicator_code,
                source_name=self.source_name,
                date=obs_date,
                value=float(raw_value),
                unit=series.unit,
                frequency=frequency,
            )
        except (PydanticValidationError, TypeError, ValueError) as exc:
            raise NormalizationError(f"could not build record: {exc}") from exc
