"""Assembles the precomputed context every AI surface narrates (decision #8).

This module is where the groundedness rule is actually *made true*. Decision #8
says the LLM narrates numbers rather than producing them, which only works if
something else produces them — this is that something. Every figure a model is
allowed to write is computed here, in Python, from stored observations, and the
same object is handed to both the prompt renderer and the verifier. One object,
two consumers: the model cannot be shown a number the verifier would reject, and
the verifier cannot accept a number the model was never shown.

Values are rounded here, once, before they reach either consumer. Rounding at the
prompt boundary instead would leave the verifier holding full precision and the
model holding a truncation of it, and every honest narration would fail.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logging_config import get_logger
from models import Anomaly, CountryProfile, DataSource, IndicatorCatalog, TimeSeries

logger = get_logger(__name__)

RECENT_POINTS = 6
ANOMALY_LIMIT = 6
#: Feature 2.3 specifies "anomaly + 12-month context"; for annual series that reads
#: as twelve periods either way, so the window is expressed in observations.
ANOMALY_WINDOW_POINTS = 12


def fmt(value: float | None) -> float | None:
    """Round for display, keeping small values precise and large ones readable.

    Both the prompt and the verifier see this output, so the precision choice is
    part of the contract rather than cosmetic.
    """
    if value is None:
        return None
    magnitude = abs(value)
    if magnitude >= 1000:
        return round(value, 0)
    if magnitude >= 10:
        return round(value, 1)
    return round(value, 2)


@dataclass(frozen=True, slots=True)
class SeriesContext:
    """Everything known about one (country, indicator), already computed."""

    indicator_id: uuid.UUID
    payload: dict[str, Any]

    @property
    def observation_count(self) -> int:
        return int(self.payload.get("observation_count", 0))


async def load_series_context(
    session: AsyncSession,
    country_code: str,
    indicator_code: str,
    *,
    include_anomalies: bool = True,
) -> SeriesContext | None:
    """Build the context object, or None if the series has no observations."""
    meta = (
        await session.execute(
            select(
                IndicatorCatalog.id,
                IndicatorCatalog.indicator_name,
                IndicatorCatalog.unit,
                IndicatorCatalog.frequency,
                DataSource.name.label("source"),
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
    if not rows:
        return None

    observations = [(r.date, float(r.value)) for r in rows]
    profile = (
        await session.execute(
            select(CountryProfile.country_name, CountryProfile.region).where(
                CountryProfile.country_code == country_code
            )
        )
    ).first()

    anomalies: list[dict[str, Any]] = []
    if include_anomalies:
        anomaly_rows = (
            await session.execute(
                select(Anomaly.date, Anomaly.value, Anomaly.z_score, Anomaly.deviation_type)
                .where(Anomaly.country_code == country_code)
                .where(Anomaly.indicator_id == meta.id)
                .order_by(Anomaly.date.desc())
                .limit(ANOMALY_LIMIT)
            )
        ).all()
        # The value each anomaly moved *from*, taken from the series already loaded
        # rather than re-queried. Without it an anomaly is a bare level with a
        # direction word attached, which is precisely how "70.8%, flagged as a drop"
        # became "a drop of 70.8%" (decision #32).
        by_date = dict(observations)
        ordered = [d for d, _ in observations]
        anomalies = []
        for a in anomaly_rows:
            value = float(a.value) if a.value is not None else None
            index = ordered.index(a.date) if a.date in by_date else None
            prev_date = ordered[index - 1] if index else None
            prev_value = by_date.get(prev_date) if prev_date else None
            anomalies.append(
                {
                    "date": a.date.isoformat(),
                    "value": fmt(value),
                    "z_score": fmt(float(a.z_score)) if a.z_score is not None else None,
                    "deviation_type": a.deviation_type or "anomaly",
                    "previous_date": prev_date.isoformat() if prev_date else None,
                    "previous_value": fmt(prev_value) if prev_value is not None else None,
                    "change_from_previous": (
                        f"{fmt(value - prev_value):+g}"
                        if value is not None and prev_value is not None
                        else None
                    ),
                }
            )

    payload = _assemble(
        country_code=country_code,
        country_name=profile.country_name if profile else country_code,
        region=profile.region if profile else None,
        indicator_code=indicator_code,
        indicator_name=meta.indicator_name,
        unit=meta.unit,
        frequency=meta.frequency,
        source=meta.source,
        observations=observations,
        anomalies=anomalies,
    )
    return SeriesContext(indicator_id=meta.id, payload=payload)


def _assemble(
    *,
    country_code: str,
    country_name: str,
    region: str | None,
    indicator_code: str,
    indicator_name: str | None,
    unit: str | None,
    frequency: str | None,
    source: str,
    observations: list[tuple[dt.date, float]],
    anomalies: list[dict[str, Any]],
) -> dict[str, Any]:
    dates = [d for d, _ in observations]
    values = [v for _, v in observations]
    min_index = values.index(min(values))
    max_index = values.index(max(values))

    return {
        "country_code": country_code,
        "country": country_name,
        "region": region,
        "indicator_code": indicator_code,
        "indicator": indicator_name or indicator_code,
        "unit": unit,
        "unit_suffix": "%" if unit == "%" else (f" {unit}" if unit else ""),
        "frequency": frequency,
        "source": source,
        "observation_count": len(observations),
        "first_date": dates[0].isoformat(),
        "last_date": dates[-1].isoformat(),
        "latest": {"date": dates[-1].isoformat(), "value": fmt(values[-1])},
        "recent": [
            {"date": d.isoformat(), "value": fmt(v)} for d, v in observations[-RECENT_POINTS:]
        ],
        "extremes": {
            "min_value": fmt(min(values)),
            "min_date": dates[min_index].isoformat(),
            "max_value": fmt(max(values)),
            "max_date": dates[max_index].isoformat(),
        },
        "changes": _changes(observations),
        "anomalies": anomalies,
    }


def _changes(observations: list[tuple[dt.date, float]]) -> dict[str, str]:
    """Period-over-period movements, computed here so the model never has to.

    Presented as pre-formatted strings with an explicit sign. The verifier reads the
    digits back out of these strings, so a narration quoting "+2.3" is grounded and
    one quoting a difference it worked out itself is not.
    """
    values = [v for _, v in observations]
    dates = [d for d, _ in observations]
    changes: dict[str, str] = {}

    for label, back in (("change since the previous period", 1), ("change over 5 periods", 5)):
        if len(values) > back:
            delta = fmt(values[-1] - values[-1 - back])
            if delta is not None:
                changes[f"{label} ({dates[-1 - back].isoformat()} to {dates[-1].isoformat()})"] = (
                    f"{delta:+g}"
                )
    return changes


def with_forecast(payload: dict[str, Any], forecast: Any | None) -> dict[str, Any]:
    """Attach a forecast to a context payload, rounded to match everything else."""
    enriched = dict(payload)
    if forecast is None:
        enriched["forecast"] = None
        return enriched
    enriched["forecast"] = {
        "model": forecast.model_used,
        "horizon": forecast.horizon,
        "points": [
            {
                "date": p.date.isoformat(),
                "median": fmt(p.median),
                "lower": fmt(p.lower),
                "upper": fmt(p.upper),
            }
            for p in forecast.points
        ],
    }
    return enriched


def anomaly_window(
    observations: list[dict[str, Any]], anomaly_date: str, span: int = ANOMALY_WINDOW_POINTS
) -> list[dict[str, Any]]:
    """The observations surrounding one anomaly, centred on it where possible."""
    index = next((i for i, point in enumerate(observations) if point["date"] == anomaly_date), None)
    if index is None:
        return observations[-span:]
    half = span // 2
    start = max(0, index - half)
    return observations[start : start + span]
