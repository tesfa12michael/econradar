"""Builds the RAG corpus (feature 2.2).

Chunks are **written as sentences containing their own numbers**, not as pointers
to rows the answering model would then have to look up. That is what makes the
retrieved evidence self-sufficient: whatever comes back from the vector search is
the complete set of facts the answer may use, and the groundedness verifier scores
the answer against exactly that text. If a chunk said "see NGA/FP.CPI.TOTL.ZG"
instead of "33.2% in 2024", the model would have nothing to cite and every number
in the answer would be a fabrication by construction.

Three chunk types, matching the `chunk_type` values the schema documents:

* `data_snapshot`  — one per (country, indicator): where it stands, where it has
  been, and how it moved recently.
* `country_profile` — one per country: identity, classification, coverage.
* `anomaly_context` — the most severe flagged observations, which is what a
  question like "where did inflation spike" needs to retrieve.

Anomalies are capped rather than exhaustive. There are ~25,400 of them; embedding
every one would add tens of megabytes to a 500 MB database to describe events no
question distinguishes between. The most extreme few per series carry the signal.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from logging_config import get_logger
from models import Anomaly, CountryProfile, DataSource, Embedding, IndicatorCatalog, TimeSeries
from services.context import fmt
from services.embeddings import EmbeddingUnavailable, embed_texts

logger = get_logger(__name__)

CHUNK_DATA_SNAPSHOT = "data_snapshot"
CHUNK_COUNTRY_PROFILE = "country_profile"
CHUNK_ANOMALY_CONTEXT = "anomaly_context"

#: Embedded in batches so one long-running job does not hold a full corpus of
#: vectors in memory on a 2 GB box.
EMBED_BATCH = 128
#: Per (country, indicator). Beyond a couple, extra anomalies restate the same event.
ANOMALIES_PER_SERIES = 2


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_key: str
    chunk_type: str
    text: str
    country_code: str | None = None
    indicator_id: uuid.UUID | None = None
    date_range_start: dt.date | None = None
    date_range_end: dt.date | None = None


def _suffix(unit: str | None) -> str:
    return "%" if unit == "%" else (f" {unit}" if unit else "")


async def build_data_snapshots(session: AsyncSession) -> list[Chunk]:
    """One chunk per (country, indicator) that has data."""
    rows = (
        await session.execute(
            select(
                TimeSeries.country_code,
                TimeSeries.indicator_id,
                IndicatorCatalog.indicator_code,
                IndicatorCatalog.indicator_name,
                IndicatorCatalog.unit,
                IndicatorCatalog.frequency,
                DataSource.name.label("source"),
                CountryProfile.country_name,
                CountryProfile.region,
                func.count().label("n"),
                func.min(TimeSeries.date).label("first_date"),
                func.max(TimeSeries.date).label("last_date"),
                func.min(TimeSeries.value).label("min_value"),
                func.max(TimeSeries.value).label("max_value"),
            )
            .join(IndicatorCatalog, TimeSeries.indicator_id == IndicatorCatalog.id)
            .join(DataSource, IndicatorCatalog.source_id == DataSource.id)
            .outerjoin(CountryProfile, CountryProfile.country_code == TimeSeries.country_code)
            .where(TimeSeries.value.is_not(None))
            .group_by(
                TimeSeries.country_code,
                TimeSeries.indicator_id,
                IndicatorCatalog.indicator_code,
                IndicatorCatalog.indicator_name,
                IndicatorCatalog.unit,
                IndicatorCatalog.frequency,
                DataSource.name,
                CountryProfile.country_name,
                CountryProfile.region,
            )
        )
    ).all()

    # One query for every series' latest value, rather than one per series: there
    # are ~3,200 of them, and the anomaly pass already learned that lesson.
    latest = {
        (r.country_code, r.indicator_id): (r.date, float(r.value))
        for r in (
            await session.execute(
                select(
                    TimeSeries.country_code,
                    TimeSeries.indicator_id,
                    TimeSeries.date,
                    TimeSeries.value,
                )
                .where(TimeSeries.value.is_not(None))
                .order_by(TimeSeries.country_code, TimeSeries.indicator_id, TimeSeries.date.desc())
                .distinct(TimeSeries.country_code, TimeSeries.indicator_id)
            )
        ).all()
    }

    chunks: list[Chunk] = []
    for r in rows:
        latest_point = latest.get((r.country_code, r.indicator_id))
        if latest_point is None:
            continue
        latest_date, latest_value = latest_point
        suffix = _suffix(r.unit)
        name = r.country_name or r.country_code
        text = (
            f"{name} ({r.country_code}) — {r.indicator_name}. "
            f"Most recent value: {fmt(latest_value)}{suffix} in {latest_date.isoformat()}. "
            f"Record covers {r.n} {r.frequency or 'periodic'} observations from "
            f"{r.first_date.isoformat()} to {r.last_date.isoformat()}, ranging from a low of "
            f"{fmt(float(r.min_value))}{suffix} to a high of {fmt(float(r.max_value))}{suffix}. "
            f"Region: {r.region or 'unclassified'}. Source: {r.source}. "
            f"Indicator code: {r.indicator_code}."
        )
        chunks.append(
            Chunk(
                chunk_key=f"{CHUNK_DATA_SNAPSHOT}:{r.country_code}:{r.indicator_code}",
                chunk_type=CHUNK_DATA_SNAPSHOT,
                text=text,
                country_code=r.country_code,
                indicator_id=r.indicator_id,
                date_range_start=r.first_date,
                date_range_end=r.last_date,
            )
        )
    return chunks


async def build_country_profiles(session: AsyncSession) -> list[Chunk]:
    """One chunk per country, so "which countries are covered" is answerable."""
    coverage = dict(
        (
            await session.execute(
                select(
                    TimeSeries.country_code, func.count(func.distinct(TimeSeries.indicator_id))
                ).group_by(TimeSeries.country_code)
            )
        )
        .tuples()
        .all()
    )
    rows = (await session.execute(select(CountryProfile))).scalars().all()

    chunks: list[Chunk] = []
    for profile in rows:
        indicators = coverage.get(profile.country_code, 0)
        region = profile.region or "an unclassified region"
        text = (
            f"{profile.country_name} ({profile.country_code}) is in {region}. "
            f"World Bank income classification: {profile.income_classification or 'unclassified'}. "
            f"IMF classification: {profile.imf_classification or 'unclassified'}. "
            f"EconRadar holds data for {indicators} indicators for this country."
        )
        chunks.append(
            Chunk(
                chunk_key=f"{CHUNK_COUNTRY_PROFILE}:{profile.country_code}",
                chunk_type=CHUNK_COUNTRY_PROFILE,
                text=text,
                country_code=profile.country_code,
            )
        )
    return chunks


async def build_anomaly_contexts(session: AsyncSession) -> list[Chunk]:
    """The most extreme flagged observation(s) per series."""
    ranked = (
        select(
            Anomaly.country_code,
            Anomaly.indicator_id,
            Anomaly.date,
            Anomaly.value,
            Anomaly.z_score,
            Anomaly.deviation_type,
            func.row_number()
            .over(
                partition_by=(Anomaly.country_code, Anomaly.indicator_id),
                order_by=(desc(func.abs(func.coalesce(Anomaly.z_score, 0))), Anomaly.date.desc()),
            )
            .label("rank"),
        )
    ).subquery()

    rows = (
        await session.execute(
            select(
                ranked.c.country_code,
                ranked.c.indicator_id,
                ranked.c.date,
                ranked.c.value,
                ranked.c.z_score,
                ranked.c.deviation_type,
                IndicatorCatalog.indicator_code,
                IndicatorCatalog.indicator_name,
                IndicatorCatalog.unit,
                CountryProfile.country_name,
            )
            .join(IndicatorCatalog, ranked.c.indicator_id == IndicatorCatalog.id)
            .outerjoin(CountryProfile, CountryProfile.country_code == ranked.c.country_code)
            .where(ranked.c.rank <= ANOMALIES_PER_SERIES)
        )
    ).all()

    chunks: list[Chunk] = []
    for r in rows:
        suffix = _suffix(r.unit)
        name = r.country_name or r.country_code
        z_phrase = (
            f"Z-score {fmt(float(r.z_score))} against its trailing window"
            if r.z_score is not None
            # Not "z-score 0": the statistic is undefined for a break, and saying
            # otherwise would put a number in the corpus that is not a measurement.
            else "classified as a structural break, for which a Z-score is undefined"
        )
        text = (
            f"Anomaly: {name} ({r.country_code}) — {r.indicator_name} was "
            f"{fmt(float(r.value)) if r.value is not None else 'unrecorded'}{suffix} "
            f"in {r.date.isoformat()}, flagged as a {r.deviation_type or 'anomaly'}, {z_phrase}. "
            f"Indicator code: {r.indicator_code}."
        )
        chunks.append(
            Chunk(
                chunk_key=f"{CHUNK_ANOMALY_CONTEXT}:{r.country_code}:{r.indicator_code}:{r.date}",
                chunk_type=CHUNK_ANOMALY_CONTEXT,
                text=text,
                country_code=r.country_code,
                indicator_id=r.indicator_id,
                date_range_start=r.date,
                date_range_end=r.date,
            )
        )
    return chunks


async def refresh_corpus(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, int]:
    """Rebuild and upsert the whole corpus. Safe to run while chat is serving."""
    async with session_factory() as session:
        chunks: list[Chunk] = []
        chunks.extend(await build_country_profiles(session))
        chunks.extend(await build_data_snapshots(session))
        chunks.extend(await build_anomaly_contexts(session))

    if not chunks:
        logger.warning("RAG corpus refresh found nothing to embed")
        return {"chunks": 0, "embedded": 0, "batches": 0}

    embedded = batches = 0
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        try:
            vectors = await embed_texts([c.text for c in batch])
        except EmbeddingUnavailable as exc:
            logger.error("RAG corpus refresh stopped: %s", exc)
            break

        async with session_factory() as session:
            stmt = pg_insert(Embedding).values(
                [
                    {
                        "chunk_key": chunk.chunk_key,
                        "chunk_type": chunk.chunk_type,
                        "chunk_text": chunk.text,
                        "country_code": chunk.country_code,
                        "indicator_id": chunk.indicator_id,
                        "embedding": vector,
                        "date_range_start": chunk.date_range_start,
                        "date_range_end": chunk.date_range_end,
                    }
                    for chunk, vector in zip(batch, vectors, strict=True)
                ]
            )
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Embedding.chunk_key],
                    set_={
                        "chunk_text": stmt.excluded.chunk_text,
                        "chunk_type": stmt.excluded.chunk_type,
                        "country_code": stmt.excluded.country_code,
                        "indicator_id": stmt.excluded.indicator_id,
                        "embedding": stmt.excluded.embedding,
                        "date_range_start": stmt.excluded.date_range_start,
                        "date_range_end": stmt.excluded.date_range_end,
                        "created_at": func.now(),
                    },
                )
            )
            await session.commit()
        embedded += len(batch)
        batches += 1

    summary = {"chunks": len(chunks), "embedded": embedded, "batches": batches}
    logger.info("RAG corpus refresh complete: %s", summary)
    return summary
