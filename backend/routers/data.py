"""Data API — countries, indicator catalog, and historical series read from Supabase.

`GET /api/v1/indicators/{country_code}?code=...` is the endpoint the Phase 1
checkpoint exercises end to end: frontend → backend → Supabase → real World Bank data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

import repositories
from db import get_session
from schemas import (
    AnomalyOut,
    CountryOut,
    IndicatorMetadataOut,
    IndicatorOptionOut,
    IndicatorSeriesOut,
    IndicatorSummaryOut,
    MapDataOut,
    RankingOut,
    SourceStatusOut,
)
from services import rankings
from services.rankings import MAX_ENTRIES

router = APIRouter(tags=["data"])


def _iso3(country_code: str) -> str:
    code = country_code.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise HTTPException(
            status_code=422, detail=f"country_code must be ISO-3 alpha, got {country_code!r}"
        )
    return code


@router.get("/countries", response_model=list[CountryOut])
async def get_countries(
    region: str | None = Query(default=None, description="Filter by World Bank region"),
    session: AsyncSession = Depends(get_session),
) -> list[CountryOut]:
    return await repositories.list_countries(session, region=region)


@router.get("/sources", response_model=list[SourceStatusOut])
async def get_sources(session: AsyncSession = Depends(get_session)) -> list[SourceStatusOut]:
    return await repositories.list_sources(session)


@router.get("/indicators", response_model=list[IndicatorOptionOut])
async def get_indicator_options(
    session: AsyncSession = Depends(get_session),
) -> list[IndicatorOptionOut]:
    """Every indicator that has data, ordered by how many countries it covers."""
    return await repositories.list_indicator_options(session)


@router.get("/indicator-metadata", response_model=list[IndicatorMetadataOut])
async def get_indicator_metadata(
    concept: str | None = Query(
        default=None, description="Filter to one concept, e.g. unemployment or government_debt"
    ),
    session: AsyncSession = Depends(get_session),
) -> list[IndicatorMetadataOut]:
    """What every ingested indicator measures, and how far it reaches.

    This is the catalog a caller consults *before* asking for a number, so that it
    picks between three unemployment series knowing one is an ILO-modelled estimate
    across 187 countries and another is a national definition across 118. Primary
    series first, then widest coverage.
    """
    return await rankings.list_indicator_metadata(session, concept=concept)


@router.get("/rankings/{indicator}", response_model=RankingOut)
async def get_rankings(
    indicator: str,
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int | None = Query(
        default=None, ge=1, le=MAX_ENTRIES, description="Trim the response; the count stays whole"
    ),
    max_age_years: int | None = Query(
        default=None,
        ge=1,
        le=100,
        description="Drop countries whose latest reading is older than this",
    ),
    session: AsyncSession = Depends(get_session),
) -> RankingOut:
    """Every country ranked on one indicator by its most recent value.

    `indicator` accepts an indicator code (`GGXWDG_NGDP`) or a concept
    (`government_debt`), and a concept resolves to the series marked primary for it
    — a choice recorded in the database with its reasoning rather than improvised
    per question.

    The ranking is always computed over the full dataset. `limit` trims the
    response after the fact and sets `truncated`, while `country_count` continues to
    report the size of the whole ranking, so a top-five request can never be
    mistaken for a statement about the world.
    """
    result = await rankings.rank_countries(
        session, indicator, order=order, limit=limit, max_age_years=max_age_years
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No indicator or concept matches {indicator!r}. "
            "GET /api/v1/indicator-metadata lists everything available.",
        )
    if not result.entries:
        raise HTTPException(
            status_code=404,
            detail=f"{result.indicator.indicator_code} has no observations matching that filter."
            + (
                f" max_age_years={max_age_years} may have excluded every country; "
                f"the series' most recent reading is {result.indicator.latest_date}."
                if max_age_years is not None
                else ""
            ),
        )
    return result


@router.get("/map", response_model=MapDataOut)
async def get_map(
    indicator: str = Query(description="Indicator code to shade the choropleth by"),
    session: AsyncSession = Depends(get_session),
) -> MapDataOut:
    """Latest value per country for one indicator, with anomaly flags."""
    data = await repositories.get_map_data(session, indicator.strip())
    if data is None:
        raise HTTPException(status_code=404, detail=f"No data for indicator {indicator!r}.")
    return data


@router.get("/anomalies", response_model=list[AnomalyOut])
async def get_anomalies(
    country: str | None = Query(default=None, description="Filter by ISO-3 country code"),
    indicator: str | None = Query(default=None, description="Filter by indicator code"),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[AnomalyOut]:
    """Statistically flagged observations — magnitude and timing only (no LLM text)."""
    return await repositories.list_anomalies(
        session,
        country_code=_iso3(country) if country else None,
        indicator_code=indicator.strip() if indicator else None,
        limit=limit,
    )


@router.get(
    "/indicators/{country_code}",
    response_model=IndicatorSeriesOut | list[IndicatorSummaryOut],
)
async def get_indicators(
    country_code: str,
    code: str | None = Query(default=None, description="Indicator code for a single series"),
    session: AsyncSession = Depends(get_session),
) -> IndicatorSeriesOut | list[IndicatorSummaryOut]:
    """With `code`: one historical series. Without: the indicators that have data
    for this country, each with its latest value."""
    iso3 = _iso3(country_code)
    if code:
        series = await repositories.get_indicator_series(session, iso3, code.strip())
        if series is None:
            raise HTTPException(
                status_code=404,
                detail=f"No data for country {iso3} / indicator {code!r}. "
                "It may not have been ingested yet.",
            )
        return series
    return await repositories.list_country_indicators(session, iso3)
