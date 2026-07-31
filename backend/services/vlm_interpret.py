"""VLM chart interpretation orchestration (feature 2.1) — render, interpret, cache.

The cache key covers the *chart*, not the request: country, indicator, the last
observation and its count, and the forecast model drawn on it. Two viewers looking
at the same chart share one interpretation; a chart that gains a point gets a new
one. TTL is seven days, per features.md 2.1.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import get_session_factory
from logging_config import get_logger
from models import Anomaly, TimeSeries
from services import prompts, singleflight
from services.cache import (
    TASK_VLM_INTERPRETATION,
    build_cache_key,
    get_cached_response,
    store_response,
)
from services.chart_render import HISTORY_POINTS, ChartRenderError, render_series_b64
from services.context import load_series_context, with_forecast
from services.forecast_store import get_forecast
from services.llm import NarrationUnavailable
from services.vlm import VLMService

logger = get_logger(__name__)

MIN_WORDS = 70
MAX_WORDS = 130


@dataclass(frozen=True, slots=True)
class ChartInterpretation:
    country_code: str
    indicator_code: str
    text: str
    provider: str
    model: str
    groundedness_score: float | None
    cached: bool


async def interpret_chart(
    session: AsyncSession,
    country_code: str,
    indicator_code: str,
    *,
    service: VLMService | None = None,
) -> ChartInterpretation | None:
    """Render this series' chart and have a vision model read it back."""
    context = await load_series_context(session, country_code, indicator_code)
    if context is None:
        return None

    forecast = await get_forecast(session, country_code, indicator_code, allow_compute=False)
    payload = with_forecast(context.payload, forecast)

    key = build_cache_key(
        TASK_VLM_INTERPRETATION,
        country=country_code,
        indicator=indicator_code,
        last_date=payload["last_date"],
        observations=payload["observation_count"],
        forecast_model=(payload.get("forecast") or {}).get("model"),
    )
    hit = await get_cached_response(session, key)
    if hit is not None:
        return ChartInterpretation(
            country_code=country_code,
            indicator_code=indicator_code,
            text=hit.text,
            provider=hit.provider or "unknown",
            model=hit.model or "unknown",
            groundedness_score=hit.groundedness_score,
            cached=True,
        )

    history = (
        await session.execute(
            select(TimeSeries.date, TimeSeries.value)
            .where(TimeSeries.country_code == country_code)
            .where(TimeSeries.indicator_id == context.indicator_id)
            .where(TimeSeries.value.is_not(None))
            .order_by(TimeSeries.date)
        )
    ).all()
    flagged = (
        await session.execute(
            select(Anomaly.date, Anomaly.value)
            .where(Anomaly.country_code == country_code)
            .where(Anomaly.indicator_id == context.indicator_id)
            .where(Anomaly.value.is_not(None))
        )
    ).all()

    try:
        image_b64 = render_series_b64(
            title=f"{payload['country']} — {payload['indicator']}",
            unit=payload["unit"],
            history=[(r.date, float(r.value)) for r in history],
            forecast=[(p.date, p.median, p.lower, p.upper) for p in forecast.points]
            if forecast
            else None,
            anomalies=[(r.date, float(r.value)) for r in flagged],
        )
    except ChartRenderError as exc:
        # Loud, per features.md 2.1 — a blank chart would be described confidently.
        logger.error("chart rendering failed for %s/%s: %s", country_code, indicator_code, exc)
        return None

    # The interpretation describes the *plotted* window, so the block it is verified
    # against must describe that window too — not the whole 60-year record.
    plotted = dict(payload)
    plotted["observation_count"] = min(payload["observation_count"], HISTORY_POINTS)
    if len(history) > HISTORY_POINTS:
        plotted["first_date"] = history[-HISTORY_POINTS].date.isoformat()

    prompt = prompts.render("vlm_chart.j2", min_words=MIN_WORDS, max_words=MAX_WORDS, **plotted)

    async def generate() -> ChartInterpretation | None:
        """One vision call per chart, shared by every concurrent viewer (decision #31).

        The most expensive of the four panels, and the most likely to be requested
        several times at once — a shared link opens the same chart for everyone who
        clicks it.
        """
        vlm = service or VLMService()
        try:
            completion = await vlm.interpret(prompt, image_b64, context=plotted)
        except NarrationUnavailable as exc:
            logger.warning(
                "VLM interpretation unavailable for %s/%s: %s", country_code, indicator_code, exc
            )
            return None

        async with get_session_factory()() as own:
            await store_response(
                own,
                cache_key=key,
                task_type=TASK_VLM_INTERPRETATION,
                response_text=completion.text,
                provider=completion.provider,
                model=completion.model,
                groundedness_score=completion.groundedness.score,
                token_count=completion.token_count,
            )
        logger.info(
            "VLM interpretation generated: %s/%s provider=%s groundedness=%.2f",
            country_code,
            indicator_code,
            completion.provider,
            completion.groundedness.score,
        )
        return ChartInterpretation(
            country_code=country_code,
            indicator_code=indicator_code,
            text=completion.text,
            provider=completion.provider,
            model=completion.model,
            groundedness_score=completion.groundedness.score,
            cached=False,
        )

    return await singleflight.run(key, generate)


def vlm_enabled() -> bool:
    return settings.llm_enabled and bool(VLMService().available())
