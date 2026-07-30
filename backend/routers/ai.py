"""Intelligence-layer API — forecasting, narration, VLM interpretation, RAG Q&A.

Grouped away from `data.py` because these routes share a property the data routes
do not: **every one of them can legitimately have nothing to return.** A model may
be unreachable, a series too short, a provider rate-limited, retrieval empty. Each
of those is a 404 with a reason, never a fabricated body — which is the API-layer
expression of decision #8.

They also share a latency profile. The design system forbids AI content blocking
page load, so the frontend calls these from separate, non-blocking panels while the
historical chart renders from `data.py` immediately.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from schemas import ForecastOut, ForecastPointOut, NarrationOut
from services.forecast_store import get_forecast
from services.narration import narrate_series

router = APIRouter(tags=["ai"])


def _iso3(country_code: str) -> str:
    code = country_code.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise HTTPException(
            status_code=422, detail=f"country_code must be ISO-3 alpha, got {country_code!r}"
        )
    return code


@router.get("/forecast/{country_code}", response_model=ForecastOut)
async def get_series_forecast(
    country_code: str,
    indicator: str = Query(description="Indicator code to forecast"),
    session: AsyncSession = Depends(get_session),
) -> ForecastOut:
    """Quantile forecast for one series (feature 1.4).

    Served from `forecast_cache` when warm. A miss walks the Chronos-2 -> TimesFM ->
    StatsForecast cascade and stores the result, so the Modal round trip is paid at
    most once per version of a series.
    """
    iso3 = _iso3(country_code)
    forecast = await get_forecast(session, iso3, indicator.strip())
    if forecast is None:
        raise HTTPException(
            status_code=404,
            detail=f"No forecast available for {iso3} / {indicator!r}. The series may "
            "be absent, too short to forecast, or every model in the cascade may have failed.",
        )
    return ForecastOut(
        country_code=forecast.country_code,
        indicator_code=forecast.indicator_code,
        indicator_name=forecast.indicator_name,
        unit=forecast.unit,
        frequency=forecast.frequency,
        model_used=forecast.model_used,
        horizon=forecast.horizon,
        points=[
            ForecastPointOut(date=p.date, median=p.median, lower=p.lower, upper=p.upper)
            for p in forecast.points
        ],
        cached=forecast.cached,
        generated_at=forecast.generated_at,
    )


@router.get("/narrate/{country_code}", response_model=NarrationOut)
async def get_narration(
    country_code: str,
    indicator: str = Query(description="Indicator code to narrate"),
    session: AsyncSession = Depends(get_session),
) -> NarrationOut:
    """Grounded commentary on one series (feature 1.5).

    Every number in the response appeared in the context the model was given;
    `groundedness_score` is the verifier's verdict on the text being returned, not a
    generic claim about the system.
    """
    iso3 = _iso3(country_code)
    narration = await narrate_series(session, iso3, indicator.strip())
    if narration is None:
        raise HTTPException(
            status_code=404,
            detail=f"No narration available for {iso3} / {indicator!r}. The series may "
            "be absent, or no provider returned a grounded response.",
        )
    return NarrationOut(
        country_code=narration.country_code,
        indicator_code=narration.indicator_code,
        text=narration.text,
        provider=narration.provider,
        model=narration.model,
        groundedness_score=narration.groundedness_score,
        cached=narration.cached,
    )
