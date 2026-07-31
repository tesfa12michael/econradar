"""Composite-key caching for every AI service (feature 2.5).

This module exists *before* the services that use it, on purpose. features.md 2.5
requires caching "built into `ForecastingService`, `LLMService`, and `VLMService`
from the start — not bolted on afterward", and a cache added later almost always
ends up wrapping a call site rather than owning the key, which is how two similar
requests quietly come to share one entry.

**Key construction.** The documented composite is country + indicator + window +
model + task type. Concatenating those with a delimiter is ambiguous — ``a:b`` + ``c``
and ``a`` + ``b:c`` produce the same string, which is exactly the "cache key collision
between similar but distinct requests" edge case features.md names. So the key is a
readable prefix (task type, country, indicator) for human inspection and
``LIKE``-scoped invalidation, followed by a digest of the *canonical JSON* of every
component. Adding a component later changes every key rather than silently colliding
with the old ones.

**Invalidation is content-addressed, not time-based** (decision #31). Every key
already digests the inputs that determine the answer — the last observation, the
observation count, the anomaly count, the forecast model. If the key matches, the
inputs are identical, so regenerating would spend a provider call to obtain the
text already stored. A short TTL therefore buys no freshness whatsoever; it only
buys the same answer again. When the data moves, the key moves with it, and the
next visitor to that country regenerates exactly once.

What a TTL is still good for is the one input the key cannot see: *this code*. A
better prompt or a stricter verifier should reach existing entries. That is what
`PROMPT_REVISION` does, deterministically and immediately, and what
`ai_cache_max_age_days` does as a slow backstop for everything else.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from logging_config import get_logger
from models import ForecastCache, LlmCache

logger = get_logger(__name__)

# task_type values, matching the llm_cache column comment in 0002_schema.sql.
TASK_NARRATION = "narration"
TASK_ANOMALY_EXPLANATION = "anomaly_explanation"
TASK_VLM_INTERPRETATION = "vlm_interpretation"
TASK_RAG_ANSWER = "rag_answer"


#: Bump when a prompt template, the context builder, or the verifier changes in a
#: way that should reach text already generated. It is part of every cache key, so
#: incrementing it retires the whole cache atomically and the replacements are
#: generated lazily, by the first visitor to each country — no sweep, no
#: regeneration of countries nobody opens.
#:
#: 1 — Phase 3 as shipped.
PROMPT_REVISION = 1


def ttl_for(task_type: str) -> dt.timedelta:
    """The safety-net age for a cached response.

    Uniform across task types, because with content-addressed keys the reason an
    entry should ever expire is the same for all of them: something changed in
    this repository that `PROMPT_REVISION` was not bumped for. Freshness of the
    *data* is handled by the key, not by the clock.
    """
    del task_type  # kept in the signature: callers pass it, and it reads as intent
    return dt.timedelta(days=settings.ai_cache_max_age_days)


def _slug(value: Any) -> str:
    """A short, delimiter-free fragment safe to read back out of a key."""
    if value is None:
        return "_"
    text = str(value)
    cleaned = "".join(c if c.isalnum() or c in "-._" else "-" for c in text)
    return cleaned[:40] or "_"


def build_cache_key(task_type: str, /, **parts: Any) -> str:
    """Readable prefix + unambiguous digest of every component.

    >>> build_cache_key("narration", country="NGA", indicator="FP.CPI.TOTL.ZG", model="mistral")
    'narration:NGA:FP.CPI.TOTL.ZG:...'
    """
    canonical = json.dumps(
        {"task": task_type, "rev": PROMPT_REVISION, **{k: parts[k] for k in sorted(parts)}},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    prefix = ":".join([task_type, _slug(parts.get("country")), _slug(parts.get("indicator"))])
    return f"{prefix}:{digest}"


# ── LLM / VLM cache ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CachedResponse:
    text: str
    provider: str | None
    model: str | None
    groundedness_score: float | None
    cached: bool = True


async def get_cached_response(session: AsyncSession, cache_key: str) -> CachedResponse | None:
    """Return a live cache entry and count the hit, or None if absent/expired."""
    row = (
        await session.execute(
            select(LlmCache).where(
                LlmCache.cache_key == cache_key,
                (LlmCache.expires_at.is_(None)) | (LlmCache.expires_at > func.now()),
            )
        )
    ).scalar_one_or_none()
    if row is None or not row.response_text:
        return None

    # Counted in SQL so concurrent hits cannot lose an increment to a read-modify-write.
    await session.execute(
        LlmCache.__table__.update()
        .where(LlmCache.id == row.id)
        .values(cache_hit_count=LlmCache.cache_hit_count + 1)
    )
    await session.commit()
    return CachedResponse(
        text=row.response_text,
        provider=row.provider_used,
        model=row.model_used,
        groundedness_score=float(row.groundedness_score)
        if row.groundedness_score is not None
        else None,
    )


async def store_response(
    session: AsyncSession,
    *,
    cache_key: str,
    task_type: str,
    response_text: str,
    provider: str | None,
    model: str | None,
    groundedness_score: float | None = None,
    token_count: int | None = None,
) -> None:
    """Upsert a generated response. Re-generating resets the TTL and the hit count."""
    expires_at = dt.datetime.now(dt.UTC) + ttl_for(task_type)
    stmt = pg_insert(LlmCache).values(
        cache_key=cache_key,
        task_type=task_type,
        provider_used=provider,
        model_used=model,
        response_text=response_text,
        groundedness_score=groundedness_score,
        token_count=token_count,
        expires_at=expires_at,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[LlmCache.cache_key],
            set_={
                "task_type": stmt.excluded.task_type,
                "provider_used": stmt.excluded.provider_used,
                "model_used": stmt.excluded.model_used,
                "response_text": stmt.excluded.response_text,
                "groundedness_score": stmt.excluded.groundedness_score,
                "token_count": stmt.excluded.token_count,
                "cache_hit_count": 0,
                "created_at": func.now(),
                "expires_at": stmt.excluded.expires_at,
            },
        )
    )
    await session.commit()


# ── Forecast cache ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CachedForecast:
    model_used: str | None
    horizon: int | None
    median: list[float]
    lower: list[float]
    upper: list[float]
    created_at: dt.datetime | None = None
    cached: bool = True


async def get_cached_forecast(session: AsyncSession, cache_key: str) -> CachedForecast | None:
    row = (
        await session.execute(
            select(ForecastCache).where(
                ForecastCache.cache_key == cache_key,
                (ForecastCache.expires_at.is_(None)) | (ForecastCache.expires_at > func.now()),
            )
        )
    ).scalar_one_or_none()
    if row is None or not row.median_forecast:
        return None
    return CachedForecast(
        model_used=row.model_used,
        horizon=row.forecast_horizon,
        median=[float(v) for v in row.median_forecast],
        lower=[float(v) for v in (row.lower_bound or [])],
        upper=[float(v) for v in (row.upper_bound or [])],
        created_at=row.created_at,
    )


async def store_forecast(
    session: AsyncSession,
    *,
    cache_key: str,
    country_code: str,
    indicator_id: uuid.UUID,
    model_used: str,
    horizon: int,
    median: list[float],
    lower: list[float],
    upper: list[float],
) -> None:
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(days=settings.forecast_cache_ttl_days)
    stmt = pg_insert(ForecastCache).values(
        cache_key=cache_key,
        country_code=country_code,
        indicator_id=indicator_id,
        model_used=model_used,
        forecast_horizon=horizon,
        median_forecast=median,
        lower_bound=lower,
        upper_bound=upper,
        expires_at=expires_at,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[ForecastCache.cache_key],
            set_={
                "model_used": stmt.excluded.model_used,
                "forecast_horizon": stmt.excluded.forecast_horizon,
                "median_forecast": stmt.excluded.median_forecast,
                "lower_bound": stmt.excluded.lower_bound,
                "upper_bound": stmt.excluded.upper_bound,
                "created_at": func.now(),
                "expires_at": stmt.excluded.expires_at,
            },
        )
    )
    await session.commit()


# ── Operations ───────────────────────────────────────────────────────────────


async def invalidate(session: AsyncSession, *, key_prefix: str) -> int:
    """Manual invalidation path (features.md 2.5's stale-after-source-correction case).

    Prefix-scoped rather than key-exact because the caller knows "everything for
    Nigeria's CPI", not the digest that a particular window produced.
    """
    removed = 0
    for table in (LlmCache, ForecastCache):
        result = await session.execute(delete(table).where(table.cache_key.like(f"{key_prefix}%")))
        removed += result.rowcount or 0
    await session.commit()
    logger.info("cache invalidated: prefix=%r removed=%d", key_prefix, removed)
    return removed


async def prune_expired(session: AsyncSession) -> int:
    """Delete rows past their safety-net age.

    Content-addressed keys mean a superseded entry is never *served* again — the
    lookup simply misses — but it is still stored. Nothing reclaims that on its
    own, so the scheduled jobs call this.

    Only expired rows are deleted, not "superseded" ones. Detecting supersession
    would mean keeping the newest key per (task, country, indicator) prefix, and
    that is wrong for `anomaly_explanation`, which legitimately holds one entry per
    anomaly under the same prefix. Age is the honest criterion; at ~1 KB a row the
    accumulation between sweeps is not material against a 500 MB budget.
    """
    removed = 0
    for table in (LlmCache, ForecastCache):
        result = await session.execute(delete(table).where(table.expires_at < func.now()))
        removed += result.rowcount or 0
    await session.commit()
    if removed:
        logger.info("cache prune: removed %d expired rows", removed)
    return removed


async def cache_stats(session: AsyncSession) -> dict[str, Any]:
    """Hit-rate and volume, for feature 2.5's measurability criterion and /status.

    Hit rate is ``hits / (hits + entries)`` — every entry cost exactly one
    generation, so entries *are* the miss count. This is the honest denominator;
    dividing hits by hits would report a rate that only ever rises.
    """
    llm = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(LlmCache.cache_hit_count), 0),
                func.avg(LlmCache.groundedness_score),
            ).where(LlmCache.expires_at > func.now())
        )
    ).one()
    forecasts = (
        await session.execute(
            select(func.count())
            .select_from(ForecastCache)
            .where(ForecastCache.expires_at > func.now())
        )
    ).scalar_one()

    entries, hits, avg_groundedness = int(llm[0]), int(llm[1]), llm[2]
    total = entries + hits
    return {
        "llm_entries": entries,
        "llm_hits": hits,
        "llm_hit_rate": round(hits / total, 3) if total else None,
        "mean_groundedness": round(float(avg_groundedness), 3)
        if avg_groundedness is not None
        else None,
        "forecast_entries": int(forecasts),
    }
