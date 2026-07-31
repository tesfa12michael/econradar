"""Narration orchestration (feature 1.5) — context, prompt, rotation, cache.

The order matters and is deliberate: build the context first, render from it,
verify against it, and only then store. Caching is not a wrapper around this
function — the key is derived from the same context the model saw (feature 2.5),
so a series that gains an observation gets a new key and a fresh narration rather
than serving prose about last month's numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import get_session_factory
from logging_config import get_logger
from services import prompts, singleflight
from services.cache import (
    TASK_NARRATION,
    build_cache_key,
    get_cached_response,
    store_response,
)
from services.context import load_series_context, with_forecast
from services.forecast_store import get_forecast
from services.llm import LLMService, NarrationUnavailable

logger = get_logger(__name__)

MIN_WORDS = 90
MAX_WORDS = 150


@dataclass(frozen=True, slots=True)
class Narration:
    country_code: str
    indicator_code: str
    text: str
    provider: str
    model: str
    groundedness_score: float | None
    cached: bool


async def narrate_series(
    session: AsyncSession,
    country_code: str,
    indicator_code: str,
    *,
    service: LLMService | None = None,
    include_forecast: bool = True,
) -> Narration | None:
    """Grounded commentary for one series, cached. None when there is nothing to say."""
    context = await load_series_context(session, country_code, indicator_code)
    if context is None:
        return None

    payload = context.payload
    if include_forecast:
        # A forecast that is not already cached is not computed here: narration must
        # not sit behind a cold GPU. The panel narrates history now and picks up the
        # forecast on a later request, once the scheduled job has warmed it.
        forecast = await get_forecast(session, country_code, indicator_code, allow_compute=False)
        payload = with_forecast(payload, forecast)
    else:
        payload = with_forecast(payload, None)

    key = build_cache_key(
        TASK_NARRATION,
        country=country_code,
        indicator=indicator_code,
        last_date=payload["last_date"],
        observations=payload["observation_count"],
        forecast_model=(payload.get("forecast") or {}).get("model"),
        anomalies=len(payload["anomalies"]),
    )

    hit = await get_cached_response(session, key)
    if hit is not None:
        return Narration(
            country_code=country_code,
            indicator_code=indicator_code,
            text=hit.text,
            provider=hit.provider or "unknown",
            model=hit.model or "unknown",
            groundedness_score=hit.groundedness_score,
            cached=True,
        )

    async def generate() -> Narration | None:
        """One generation per key, shared by every concurrent caller (decision #31).

        Writes through a session of its own: the callers waiting on this are each
        holding their own, and an `AsyncSession` is not safe to share between tasks.
        """
        user_prompt = prompts.render(
            "narration.j2", min_words=MIN_WORDS, max_words=MAX_WORDS, **payload
        )
        llm = service or LLMService()
        try:
            completion = await llm.narrate(prompts.chat_messages(user_prompt), context=payload)
        except NarrationUnavailable as exc:
            # Nothing is stored and nothing is invented: the panel reports that
            # narration is unavailable, which is true, rather than showing text
            # nobody verified.
            logger.warning("narration unavailable for %s/%s: %s", country_code, indicator_code, exc)
            return None

        async with get_session_factory()() as own:
            await store_response(
                own,
                cache_key=key,
                task_type=TASK_NARRATION,
                response_text=completion.text,
                provider=completion.provider,
                model=completion.model,
                groundedness_score=completion.groundedness.score,
                token_count=completion.token_count,
            )
        logger.info(
            "narration generated: %s/%s provider=%s groundedness=%.2f numbers=%d",
            country_code,
            indicator_code,
            completion.provider,
            completion.groundedness.score,
            completion.groundedness.total_numbers,
        )
        return Narration(
            country_code=country_code,
            indicator_code=indicator_code,
            text=completion.text,
            provider=completion.provider,
            model=completion.model,
            groundedness_score=completion.groundedness.score,
            cached=False,
        )

    return await singleflight.run(key, generate)


def narration_enabled() -> bool:
    """Whether any provider is configured — used by /status and the frontend panel."""
    return settings.llm_enabled and bool(LLMService().available())
