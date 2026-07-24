"""Data API — countries, indicator catalog, and historical series read from Supabase.

`GET /api/v1/indicators/{country_code}?code=...` is the endpoint the Phase 1
checkpoint exercises end to end: frontend → backend → Supabase → real World Bank data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

import repositories
from db import get_session
from schemas import CountryOut, IndicatorSeriesOut, IndicatorSummaryOut, SourceStatusOut

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
