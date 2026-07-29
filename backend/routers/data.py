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
    IndicatorOptionOut,
    IndicatorSeriesOut,
    IndicatorSummaryOut,
    MapDataOut,
    SourceStatusOut,
)

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
