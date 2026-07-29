"""Health and sanitized public status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

import repositories
from config import settings
from db import check_db, get_session
from logging_config import get_logger
from scheduler import scheduler_status
from schemas import HealthOut, StatusOut

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Liveness + dependency snapshot. Never fails, even if the DB is down."""
    if not settings.database_url:
        database = "not_configured"
    else:
        database = "connected" if await check_db() else "unavailable"
    return HealthOut(
        status="ok",
        environment=settings.environment,
        version=settings.app_version,
        database=database,
        scheduler=scheduler_status(),
    )


@router.get("/status", response_model=StatusOut)
async def status(session: AsyncSession = Depends(get_session)) -> StatusOut:
    """Sanitized public status (design-system Flow 3) — aggregates only, no internals."""
    try:
        countries = await repositories.count_countries(session)
        indicators = await repositories.count_indicators(session)
        observations = await repositories.count_observations(session)
        anomalies = await repositories.count_anomalies(session)
        sources = await repositories.list_sources(session)
        overall = "operational"
    except Exception as exc:
        logger.warning("status endpoint degraded: %s", exc)
        return StatusOut(
            status="degraded",
            environment=settings.environment,
            countries_tracked=0,
            indicators_tracked=0,
            sources=[],
        )
    return StatusOut(
        status=overall,
        environment=settings.environment,
        countries_tracked=countries,
        indicators_tracked=indicators,
        observations_tracked=observations,
        anomalies_flagged=anomalies,
        sources=sources,
    )
