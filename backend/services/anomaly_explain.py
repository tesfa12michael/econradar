"""LLM-grounded anomaly explanations (feature 2.3).

Writes `anomalies.llm_explanation`, the column Phase 2 built and deliberately
preserved: anomaly retraction is timestamp-based rather than delete-and-reinsert
precisely so a re-score does not discard an expensive explanation.

**Generated on view, not in bulk.** features.md 2.3 asks that every stored anomaly
have an explanation. There are ~25,400 of them, which is not a rounding error away
from any free tier — it is roughly seven hours of continuous generation for series
nobody has opened. So an explanation is produced the first time an anomaly is
actually surfaced, and then persists in the column indefinitely. The guarantee that
holds in practice is the one that matters: **no anomaly is ever displayed without a
grounded explanation beside it.** The scope change is recorded in features.md
rather than left for someone to discover.

**The prompt forbids naming a cause**, and that is the substantive part. Asked why
Nigerian inflation spiked in 1995, a model will happily supply a plausible policy
or currency explanation that is nowhere in the data — a fabrication the numeric
verifier cannot see, because it contains no numbers. The instruction is explicit
and the acceptable ending is "the data does not say why".
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from logging_config import get_logger
from models import Anomaly, CountryProfile, DataSource, IndicatorCatalog, TimeSeries
from services import prompts
from services.cache import (
    TASK_ANOMALY_EXPLANATION,
    build_cache_key,
    store_response,
)
from services.context import ANOMALY_WINDOW_POINTS, anomaly_window, fmt
from services.llm import LLMService, NarrationUnavailable

logger = get_logger(__name__)

MIN_WORDS = 45
MAX_WORDS = 90


@dataclass(frozen=True, slots=True)
class AnomalyExplanation:
    country_code: str
    indicator_code: str
    date: dt.date
    value: float | None
    z_score: float | None
    deviation_type: str | None
    explanation: str | None
    cached: bool


async def _series_meta(
    session: AsyncSession, indicator_code: str
) -> tuple[uuid.UUID, str | None, str | None, str] | None:
    row = (
        await session.execute(
            select(
                IndicatorCatalog.id,
                IndicatorCatalog.indicator_name,
                IndicatorCatalog.unit,
                DataSource.name.label("source"),
            )
            .join(DataSource, IndicatorCatalog.source_id == DataSource.id)
            .where(IndicatorCatalog.indicator_code == indicator_code)
            .limit(1)
        )
    ).first()
    return (row.id, row.indicator_name, row.unit, row.source) if row else None


async def explain_anomalies(
    session: AsyncSession,
    country_code: str,
    indicator_code: str,
    *,
    limit: int = 3,
    service: LLMService | None = None,
) -> list[AnomalyExplanation]:
    """Explanations for the most notable anomalies in one series.

    Ordered by absolute Z-score so the ones a reader would ask about first are the
    ones that get written. A structural break has no Z-score by construction
    (the statistic is undefined, not merely large), so it sorts last rather than
    being treated as a zero-magnitude event.
    """
    meta = await _series_meta(session, indicator_code)
    if meta is None:
        return []
    indicator_id, indicator_name, unit, source = meta

    rows = (
        await session.execute(
            select(
                Anomaly.id,
                Anomaly.date,
                Anomaly.value,
                Anomaly.z_score,
                Anomaly.deviation_type,
                Anomaly.llm_explanation,
            )
            .where(Anomaly.country_code == country_code)
            .where(Anomaly.indicator_id == indicator_id)
            .order_by(
                # NULLs last: a structural break has no Z-score because the statistic
                # is undefined there, not because the move was small.
                Anomaly.z_score.is_(None),
                desc(func.abs(Anomaly.z_score)),
                Anomaly.date.desc(),
            )
            .limit(limit)
        )
    ).all()
    if not rows:
        return []

    observations = (
        await session.execute(
            select(TimeSeries.date, TimeSeries.value)
            .where(TimeSeries.country_code == country_code)
            .where(TimeSeries.indicator_id == indicator_id)
            .where(TimeSeries.value.is_not(None))
            .order_by(TimeSeries.date)
        )
    ).all()
    points = [{"date": r.date.isoformat(), "value": fmt(float(r.value))} for r in observations]

    country_name = (
        await session.execute(
            select(CountryProfile.country_name).where(CountryProfile.country_code == country_code)
        )
    ).scalar_one_or_none() or country_code

    all_flagged = [
        {
            "date": r.date.isoformat(),
            "value": fmt(float(r.value)) if r.value is not None else None,
            "deviation_type": r.deviation_type or "anomaly",
        }
        for r in rows
    ]

    llm = service or LLMService()
    results: list[AnomalyExplanation] = []
    for row in rows:
        if row.llm_explanation:
            results.append(_to_result(row, country_code, indicator_code, cached=True))
            continue

        explanation = await _generate(
            session,
            llm=llm,
            anomaly_id=row.id,
            country_code=country_code,
            country_name=country_name,
            indicator_code=indicator_code,
            indicator_name=indicator_name,
            unit=unit,
            source=source,
            row=row,
            points=points,
            all_flagged=all_flagged,
        )
        results.append(
            AnomalyExplanation(
                country_code=country_code,
                indicator_code=indicator_code,
                date=row.date,
                value=float(row.value) if row.value is not None else None,
                z_score=float(row.z_score) if row.z_score is not None else None,
                deviation_type=row.deviation_type,
                explanation=explanation,
                cached=False,
            )
        )
    return results


def _to_result(
    row: Any, country_code: str, indicator_code: str, *, cached: bool
) -> AnomalyExplanation:
    return AnomalyExplanation(
        country_code=country_code,
        indicator_code=indicator_code,
        date=row.date,
        value=float(row.value) if row.value is not None else None,
        z_score=float(row.z_score) if row.z_score is not None else None,
        deviation_type=row.deviation_type,
        explanation=row.llm_explanation,
        cached=cached,
    )


async def _generate(
    session: AsyncSession,
    *,
    llm: LLMService,
    anomaly_id: uuid.UUID,
    country_code: str,
    country_name: str,
    indicator_code: str,
    indicator_name: str | None,
    unit: str | None,
    source: str,
    row: Any,
    points: list[dict[str, Any]],
    all_flagged: list[dict[str, Any]],
) -> str | None:
    """One explanation: build context, render, rotate, verify, persist."""
    anomaly = {
        "date": row.date.isoformat(),
        "value": fmt(float(row.value)) if row.value is not None else None,
        "z_score": fmt(float(row.z_score)) if row.z_score is not None else None,
        "deviation_type": row.deviation_type or "anomaly",
    }
    window = anomaly_window(points, anomaly["date"], ANOMALY_WINDOW_POINTS)
    context = {
        "country": country_name,
        "indicator": indicator_name or indicator_code,
        "unit": unit,
        "unit_suffix": "%" if unit == "%" else (f" {unit}" if unit else ""),
        "source": source,
        "anomaly": anomaly,
        "window": window,
        "other_anomalies": [a for a in all_flagged if a["date"] != anomaly["date"]],
    }

    user_prompt = prompts.render(
        "anomaly_explanation.j2", min_words=MIN_WORDS, max_words=MAX_WORDS, **context
    )
    try:
        completion = await llm.narrate(prompts.chat_messages(user_prompt), context=context)
    except NarrationUnavailable as exc:
        logger.warning(
            "anomaly explanation unavailable for %s/%s %s: %s",
            country_code,
            indicator_code,
            anomaly["date"],
            exc,
        )
        return None

    # The column is the durable home — it survives re-scoring, which is why
    # retraction is timestamp-based. llm_cache records the same text for the
    # cache-hit-rate metrics feature 2.5 has to expose.
    await session.execute(
        update(Anomaly).where(Anomaly.id == anomaly_id).values(llm_explanation=completion.text)
    )
    await session.commit()
    await store_response(
        session,
        cache_key=build_cache_key(
            TASK_ANOMALY_EXPLANATION,
            country=country_code,
            indicator=indicator_code,
            date=anomaly["date"],
            value=anomaly["value"],
        ),
        task_type=TASK_ANOMALY_EXPLANATION,
        response_text=completion.text,
        provider=completion.provider,
        model=completion.model,
        groundedness_score=completion.groundedness.score,
        token_count=completion.token_count,
    )
    logger.info(
        "anomaly explanation written: %s/%s %s provider=%s groundedness=%.2f",
        country_code,
        indicator_code,
        anomaly["date"],
        completion.provider,
        completion.groundedness.score,
    )
    return completion.text
