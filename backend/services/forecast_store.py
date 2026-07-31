"""Persistence and orchestration for feature 1.4.

Kept separate from `services/forecasting.py` for the same reason `anomaly_store.py`
is separate from `anomaly.py`: the numerics stay pure and testable without a
database, and every statement that touches Supabase lives in one file. That
separation is also what makes decision #21's boundary checkable by reading —
Modal is called from the service, and only this module writes.

Dates are computed **here**, never by the model host. Modal receives values and
returns values; deciding that the next annual point after 2025-01-01 is 2026-01-01
is the database's business, not a GPU's.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from db import get_session_factory
from logging_config import get_logger
from models import DataSource, IndicatorCatalog, TimeSeries
from services import singleflight
from services.cache import build_cache_key, get_cached_forecast, store_forecast
from services.forecasting import (
    ForecastingService,
    ForecastUnavailable,
    horizon_for,
    seasonality_for,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    date: dt.date
    median: float
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class Forecast:
    country_code: str
    indicator_code: str
    indicator_name: str | None
    unit: str | None
    frequency: str | None
    model_used: str
    horizon: int
    points: list[ForecastPoint]
    cached: bool
    generated_at: dt.datetime | None = None


def advance(date: dt.date, frequency: str | None, steps: int) -> dt.date:
    """The date `steps` periods after `date`, normalised to the period's first day.

    Mirrors `connectors/dates.py`: every stored observation sits on the first day of
    its period, so a forecast point must too or the chart will show the projection
    offset from the history it continues.
    """
    freq = (frequency or "annual").lower()
    if freq == "monthly":
        month_index = (date.year * 12 + date.month - 1) + steps
        return dt.date(month_index // 12, month_index % 12 + 1, 1)
    if freq == "quarterly":
        month_index = (date.year * 12 + date.month - 1) + 3 * steps
        return dt.date(month_index // 12, month_index % 12 + 1, 1)
    return dt.date(date.year + steps, date.month, 1)


async def _load_series(
    session: AsyncSession, country_code: str, indicator_code: str
) -> tuple[uuid.UUID, str | None, str | None, str | None, list[tuple[dt.date, float]]] | None:
    """History for one (country, indicator), newest last, nulls excluded."""
    meta = (
        await session.execute(
            select(
                IndicatorCatalog.id,
                IndicatorCatalog.indicator_name,
                IndicatorCatalog.unit,
                IndicatorCatalog.frequency,
            )
            .join(DataSource, IndicatorCatalog.source_id == DataSource.id)
            .where(IndicatorCatalog.indicator_code == indicator_code)
            .limit(1)
        )
    ).first()
    if meta is None:
        return None

    rows = (
        await session.execute(
            select(TimeSeries.date, TimeSeries.value)
            .where(TimeSeries.country_code == country_code)
            .where(TimeSeries.indicator_id == meta.id)
            .where(TimeSeries.value.is_not(None))
            .order_by(TimeSeries.date)
        )
    ).all()
    return (
        meta.id,
        meta.indicator_name,
        meta.unit,
        meta.frequency,
        [(r.date, float(r.value)) for r in rows],
    )


def forecast_cache_key(
    country_code: str, indicator_code: str, last_date: dt.date, n_obs: int, horizon: int
) -> str:
    """Composite key (feature 2.5).

    `last_date` and `n_obs` are part of the key on purpose: when a source corrects
    or extends a series, the key changes and the next request regenerates. That
    closes features.md 2.5's "stale cache serving outdated data after a source
    correction" edge case structurally, instead of relying on the TTL being short
    enough — which for a 30-day forecast TTL it would not be.
    """
    return build_cache_key(
        "forecast",
        country=country_code,
        indicator=indicator_code,
        last_date=last_date.isoformat(),
        observations=n_obs,
        horizon=horizon,
        cascade=list(ForecastingService.MODEL_CASCADE),
    )


async def get_forecast(
    session: AsyncSession,
    country_code: str,
    indicator_code: str,
    *,
    service: ForecastingService | None = None,
    allow_compute: bool = True,
) -> Forecast | None:
    """Cached forecast for one series, computing it on a miss.

    Returns None when the series does not exist or is too short to forecast — the
    caller renders "not available" rather than a fabricated projection.
    """
    loaded = await _load_series(session, country_code, indicator_code)
    if loaded is None:
        return None
    indicator_id, name, unit, frequency, history = loaded
    if len(history) < settings.forecast_min_observations:
        logger.info(
            "forecast skipped: %s/%s has %d observations (min %d)",
            country_code,
            indicator_code,
            len(history),
            settings.forecast_min_observations,
        )
        return None

    horizon = horizon_for(frequency)
    last_date = history[-1][0]
    key = forecast_cache_key(country_code, indicator_code, last_date, len(history), horizon)

    def assemble_cached(entry: Any) -> Forecast:
        return _assemble(
            country_code,
            indicator_code,
            name,
            unit,
            frequency,
            last_date,
            entry.model_used or "unknown",
            entry.median,
            entry.lower,
            entry.upper,
            cached=True,
            generated_at=entry.created_at,
        )

    cached = await get_cached_forecast(session, key)
    if cached is not None:
        return assemble_cached(cached)

    if not allow_compute:
        # Borrow, never start (decision #31). The narration and chart-analysis panels
        # arrive at the same moment as the forecast panel and want the same forecast.
        # Waiting for one already in flight costs nothing and saves a second
        # generation of every panel that mentions it; starting one here would put a
        # cold GPU on a path that is explicitly not allowed to.
        if (
            await singleflight.await_in_flight(key, timeout=settings.forecast_borrow_wait_seconds)
            is not None
        ):
            borrowed = await get_cached_forecast(session, key)
            if borrowed is not None:
                logger.info("forecast borrowed from an in-flight computation: %s", key)
                return assemble_cached(borrowed)
        return None

    svc = service or ForecastingService()
    history_values = [v for _, v in history]

    async def compute_and_store() -> bool:
        """Own the computation and the write, on a session of its own.

        A single `AsyncSession` cannot be shared between concurrent tasks, and the
        whole point here is that several requests are waiting. So the winner writes
        through its own session and every caller — winner included — re-reads the
        row afterwards.
        """
        try:
            result = await svc.predict(
                history_values, horizon=horizon, seasonality=seasonality_for(frequency)
            )
        except ForecastUnavailable as exc:
            logger.warning("forecast unavailable for %s/%s: %s", country_code, indicator_code, exc)
            return False
        async with get_session_factory()() as own:
            await store_forecast(
                own,
                cache_key=key,
                country_code=country_code,
                indicator_id=indicator_id,
                model_used=result.model_used,
                horizon=horizon,
                median=result.median,
                lower=result.lower,
                upper=result.upper,
            )
        return True

    produced = await singleflight.run(key, compute_and_store)
    if not produced:
        return None

    stored = await get_cached_forecast(session, key)
    if stored is None:
        # Written and immediately not readable would mean the row was pruned or the
        # write rolled back; either way there is nothing to serve.
        logger.error("forecast stored but not readable back for %s", key)
        return None
    return _assemble(
        country_code,
        indicator_code,
        name,
        unit,
        frequency,
        last_date,
        stored.model_used or "unknown",
        stored.median,
        stored.lower,
        stored.upper,
        cached=False,
        generated_at=stored.created_at,
    )


def _assemble(
    country_code: str,
    indicator_code: str,
    name: str | None,
    unit: str | None,
    frequency: str | None,
    last_date: dt.date,
    model_used: str,
    median: list[float],
    lower: list[float],
    upper: list[float],
    *,
    cached: bool,
    generated_at: dt.datetime | None,
) -> Forecast:
    points = [
        ForecastPoint(
            date=advance(last_date, frequency, step),
            median=m,
            lower=lo if lo <= m else m,
            upper=up if up >= m else m,
        )
        for step, (m, lo, up) in enumerate(zip(median, lower, upper, strict=False), start=1)
    ]
    return Forecast(
        country_code=country_code,
        indicator_code=indicator_code,
        indicator_name=name,
        unit=unit,
        frequency=frequency,
        model_used=model_used,
        horizon=len(points),
        points=points,
        cached=cached,
        generated_at=generated_at,
    )


async def refresh_forecasts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    countries: tuple[str, ...] | None = None,
    max_series: int = 400,
) -> dict[str, int]:
    """Pre-compute forecasts for the covered countries (the scheduled job).

    Deliberately scoped rather than exhaustive: forecasting every stored
    (country, indicator) pair would be thousands of GPU calls a week for series
    nobody opens. Pre-warming the focus set keeps the common request a cache hit,
    and anything outside it is computed on first view and then cached like any other.
    """
    scope = countries or settings.forecast_countries
    service = ForecastingService()
    computed = cached = skipped = failed = 0

    async with session_factory() as session:
        pairs = (
            await session.execute(
                select(TimeSeries.country_code, IndicatorCatalog.indicator_code)
                .join(IndicatorCatalog, TimeSeries.indicator_id == IndicatorCatalog.id)
                .where(TimeSeries.country_code.in_(scope))
                .group_by(TimeSeries.country_code, IndicatorCatalog.indicator_code)
                .order_by(TimeSeries.country_code, IndicatorCatalog.indicator_code)
                .limit(max_series)
            )
        ).all()

    for country_code, indicator_code in pairs:
        # A fresh session per series: one long-lived session across hundreds of Modal
        # round trips would hold a pooled Supabase connection open for the whole job.
        async with session_factory() as session:
            try:
                before = await get_forecast(
                    session, country_code, indicator_code, service=service, allow_compute=False
                )
                if before is not None:
                    cached += 1
                    continue
                result = await get_forecast(session, country_code, indicator_code, service=service)
            except Exception as exc:
                failed += 1
                logger.exception(
                    "forecast refresh failed for %s/%s: %s", country_code, indicator_code, exc
                )
                continue
        if result is None:
            skipped += 1
        else:
            computed += 1

    summary = {
        "series_considered": len(pairs),
        "computed": computed,
        "already_cached": cached,
        "skipped": skipped,
        "failed": failed,
    }
    logger.info("forecast refresh complete: %s", summary)
    return summary
