"""Global rankings and indicator metadata — the query surface the agent reasons over.

Two problems live here, and they are the same problem seen from two sides.

**A superlative is a claim about a dataset, not about a retrieval.** Asked which
country has the highest debt-to-GDP, a system that answers from whatever chunks a
vector search returned will name whichever country happened to be in them. That
is not a wrong retrieval — the fragment it quoted was real — it is a wrong *kind
of answer*, and no amount of better retrieval fixes it, because the question is
about all 194 countries and retrieval is definitionally a subset. So a superlative
has to be answered by a query that reads every country, every time.

**And a ranking is only meaningful if every country in it was measured the same
way.** This catalog holds two debt series: IMF general government (194 countries)
and World Bank central government (109). Ranking across a mix of the two would put
federal states artificially low and be wrong in a way that looks completely
plausible. So a ranking is always over one indicator, it always reports which one,
and it names the alternatives that measure the same concept differently.

`country_count` is reported even when `entries` is truncated, and `truncated` says
so outright. A caller asking for the top five is told it is seeing five of 194.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from logging_config import get_logger
from models import DataSource, IndicatorCatalog, TimeSeries
from schemas import IndicatorMetadataOut, RankingEntryOut, RankingOut

logger = get_logger(__name__)

#: A ranking never exceeds one row per country, so this bounds a response by the
#: shape of the data rather than by an arbitrary page size.
MAX_ENTRIES = 300


async def list_indicator_metadata(
    session: AsyncSession,
    *,
    concept: str | None = None,
    indicator_code: str | None = None,
) -> list[IndicatorMetadataOut]:
    """Every ingested indicator with its full measurement metadata and coverage.

    Coverage is part of the metadata rather than a separate call because it is part
    of choosing: a 194-country series and a 109-country series measuring almost the
    same thing are not equally good answers to "which country has the most".
    """
    described = (
        IndicatorCatalog.indicator_code,
        IndicatorCatalog.indicator_name,
        IndicatorCatalog.category,
        IndicatorCatalog.unit,
        IndicatorCatalog.frequency,
        IndicatorCatalog.concept,
        IndicatorCatalog.metric_type,
        IndicatorCatalog.transformation,
        IndicatorCatalog.observation_basis,
        IndicatorCatalog.price_basis,
        IndicatorCatalog.coverage_definition,
        IndicatorCatalog.seasonal_adjustment,
        IndicatorCatalog.is_primary_for_concept,
        IndicatorCatalog.comparability_notes,
        DataSource.name.label("source"),
    )
    stmt = (
        select(
            *described,
            func.count(func.distinct(TimeSeries.country_code)).label("country_count"),
            func.count(TimeSeries.value).label("observation_count"),
            func.min(TimeSeries.date).label("earliest_date"),
            func.max(TimeSeries.date).label("latest_date"),
        )
        .join(DataSource, IndicatorCatalog.source_id == DataSource.id)
        .join(TimeSeries, TimeSeries.indicator_id == IndicatorCatalog.id)
        .group_by(*described)
    )
    if concept:
        stmt = stmt.where(IndicatorCatalog.concept == concept.strip().lower())
    if indicator_code:
        stmt = stmt.where(IndicatorCatalog.indicator_code == indicator_code.strip())

    rows = (await session.execute(stmt)).all()
    out = [
        IndicatorMetadataOut(
            indicator_code=r.indicator_code,
            indicator_name=r.indicator_name,
            source=r.source,
            unit=r.unit,
            frequency=r.frequency,
            category=r.category,
            concept=r.concept,
            metric_type=r.metric_type,
            transformation=r.transformation,
            observation_basis=r.observation_basis,
            price_basis=r.price_basis,
            coverage_definition=r.coverage_definition,
            seasonal_adjustment=r.seasonal_adjustment,
            is_primary_for_concept=bool(r.is_primary_for_concept),
            comparability_notes=r.comparability_notes,
            country_count=r.country_count,
            observation_count=r.observation_count,
            earliest_date=r.earliest_date,
            latest_date=r.latest_date,
        )
        for r in rows
    ]
    # Primary first, then widest coverage: the order a caller should consider them in.
    out.sort(key=lambda m: (not m.is_primary_for_concept, -m.country_count))
    return out


async def resolve_indicator(session: AsyncSession, token: str) -> IndicatorMetadataOut | None:
    """Find an indicator from a code or from a concept name.

    Accepting a concept is not a convenience. A caller that has to guess an exact
    code guesses wrong, and the wrong guess here is not a 404 — it is a plausible
    ranking on the wrong measurement. Given "government_debt" this returns the
    series marked primary for that concept, which is a decision recorded in the
    database with its reasoning, rather than one improvised at question time.
    """
    token = (token or "").strip()
    if not token:
        return None

    exact = await list_indicator_metadata(session, indicator_code=token)
    if exact:
        return exact[0]

    by_concept = await list_indicator_metadata(session, concept=token.replace("-", "_"))
    if by_concept:
        # list_indicator_metadata sorts primary first.
        return by_concept[0]

    # Case-insensitive code match, last: codes are conventionally upper case, and
    # falling back to it before the concept lookup would shadow a concept name.
    folded = token.casefold()
    for meta in await list_indicator_metadata(session):
        if meta.indicator_code.casefold() == folded:
            return meta
    return None


async def rank_countries(
    session: AsyncSession,
    indicator_token: str,
    *,
    order: str = "desc",
    limit: int | None = None,
    max_age_years: int | None = None,
) -> RankingOut | None:
    """Every country ranked on one indicator by its most recent value.

    Reads `v_latest_observations`, which is the whole dataset by construction —
    there is no code path here that ranks a subset, because there is no parameter
    that would let a caller ask for one. `limit` truncates what is *returned* after
    the full ranking has been computed and counted.
    """
    meta = await resolve_indicator(session, indicator_token)
    if meta is None:
        return None

    direction = "asc" if str(order).lower() == "asc" else "desc"
    params: dict[str, object] = {"code": meta.indicator_code}
    cutoff_clause = ""
    if max_age_years is not None:
        params["cutoff"] = dt.date.today() - dt.timedelta(days=365 * max_age_years)
        cutoff_clause = " and observation_date >= :cutoff"

    rows = (
        await session.execute(
            text(
                "select country_code, country_name, region, value, observation_date, source "
                "from v_latest_observations "
                f"where indicator_code = :code{cutoff_clause} "
                f"order by value {direction}, country_code asc"
            ),
            params,
        )
    ).all()

    entries = [
        RankingEntryOut(
            rank=i,
            country_code=r.country_code,
            country_name=r.country_name,
            region=r.region,
            value=float(r.value),
            observation_date=r.observation_date,
            source=r.source,
        )
        for i, r in enumerate(rows, start=1)
    ]
    dates = [e.observation_date for e in entries]

    kept = entries if limit is None else entries[: max(1, min(limit, MAX_ENTRIES))]
    logger.info(
        "ranking: %s (%s) over %d countries, returning %d, order=%s",
        meta.indicator_code,
        meta.concept,
        len(entries),
        len(kept),
        direction,
    )
    return RankingOut(
        indicator=meta,
        order=direction,
        # The size of the ranking, not of the response. Reported alongside
        # `truncated` so a top-5 request cannot be mistaken for the whole world.
        country_count=len(entries),
        truncated=len(kept) < len(entries),
        earliest_observation=min(dates) if dates else None,
        latest_observation=max(dates) if dates else None,
        entries=kept,
        alternative_indicators=[
            alt
            for alt in await list_indicator_metadata(session, concept=meta.concept or "")
            if alt.indicator_code != meta.indicator_code
        ],
    )
