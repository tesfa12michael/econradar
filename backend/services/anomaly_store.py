"""Persistence for feature 1.8 — run detection over stored series and upsert results.

Kept separate from `services/anomaly.py` so the statistics stay pure and unit-testable
without a database, while all SQL lives here.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from logging_config import get_logger
from models import Anomaly as AnomalyRow
from models import DataSource, TimeSeries
from services.anomaly import Observation, detect

logger = get_logger(__name__)

_UPSERT_CHUNK = 500


async def _series_keys(
    session: AsyncSession, source_name: str | None
) -> list[tuple[str, uuid.UUID]]:
    """Every (country_code, indicator_id) pair that has stored observations."""
    stmt = select(TimeSeries.country_code, TimeSeries.indicator_id).distinct()
    if source_name:
        stmt = stmt.join(DataSource, TimeSeries.source_id == DataSource.id).where(
            DataSource.name == source_name
        )
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


async def _observations(
    session: AsyncSession, country_code: str, indicator_id: uuid.UUID
) -> list[Observation]:
    stmt = (
        select(TimeSeries.date, TimeSeries.value)
        .where(TimeSeries.country_code == country_code)
        .where(TimeSeries.indicator_id == indicator_id)
        .where(TimeSeries.value.is_not(None))
        .order_by(TimeSeries.date)
    )
    return [
        Observation(date=row.date, value=float(row.value))
        for row in (await session.execute(stmt)).all()
    ]


async def refresh_anomalies(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_name: str | None = None,
) -> dict[str, int]:
    """Re-score every series (optionally just one source's) and upsert the anomalies.

    Returns a small JSON-friendly summary so scheduled job history stays legible.
    """
    async with session_factory() as session:
        keys = await _series_keys(session, source_name)

        payload: list[dict] = []
        for country_code, indicator_id in keys:
            observations = await _observations(session, country_code, indicator_id)
            for anomaly in detect(observations):
                payload.append(
                    {
                        "country_code": country_code,
                        "indicator_id": indicator_id,
                        "date": anomaly.date,
                        "value": anomaly.value,
                        "z_score": anomaly.z_score,
                        "deviation_type": anomaly.deviation_type,
                    }
                )

        for start in range(0, len(payload), _UPSERT_CHUNK):
            chunk = payload[start : start + _UPSERT_CHUNK]
            ins = pg_insert(AnomalyRow).values(chunk)
            await session.execute(
                ins.on_conflict_do_update(
                    constraint="anomalies_natural_key",
                    set_={
                        "value": ins.excluded.value,
                        "z_score": ins.excluded.z_score,
                        "deviation_type": ins.excluded.deviation_type,
                        "detected_at": text("now()"),
                    },
                )
            )
        await session.commit()

    logger.info(
        "anomaly refresh complete: series=%d anomalies=%d source=%s",
        len(keys),
        len(payload),
        source_name or "all",
    )
    return {"series_scanned": len(keys), "anomalies": len(payload)}


async def count_anomalies(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(AnomalyRow))).scalar_one()
