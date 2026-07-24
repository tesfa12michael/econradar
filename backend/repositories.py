"""Read-side data access for the API. Thin, typed queries over the ORM so routers
stay declarative and this layer can be exercised directly in tests.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import CountryProfile, DataSource, IndicatorCatalog, TimeSeries
from schemas import (
    CountryOut,
    IndicatorSeriesOut,
    IndicatorSummaryOut,
    ObservationOut,
    SourceStatusOut,
)


async def list_countries(session: AsyncSession, region: str | None = None) -> list[CountryOut]:
    stmt = select(CountryProfile).order_by(CountryProfile.country_name)
    if region:
        stmt = stmt.where(CountryProfile.region == region)
    rows = (await session.execute(stmt)).scalars().all()
    return [CountryOut.model_validate(r) for r in rows]


async def count_countries(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(CountryProfile))).scalar_one()


async def count_indicators(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(IndicatorCatalog))).scalar_one()


async def list_sources(session: AsyncSession) -> list[SourceStatusOut]:
    rows = (await session.execute(select(DataSource).order_by(DataSource.name))).scalars().all()
    return [
        SourceStatusOut(
            name=r.name, is_active=r.is_active, last_successful_run=r.last_successful_run
        )
        for r in rows
    ]


async def get_indicator_series(
    session: AsyncSession, country_code: str, indicator_code: str
) -> IndicatorSeriesOut | None:
    stmt = (
        select(
            TimeSeries.date,
            TimeSeries.value,
            TimeSeries.is_validated,
            IndicatorCatalog.indicator_name,
            IndicatorCatalog.unit,
            DataSource.name.label("source"),
        )
        .join(IndicatorCatalog, TimeSeries.indicator_id == IndicatorCatalog.id)
        .join(DataSource, TimeSeries.source_id == DataSource.id)
        .where(TimeSeries.country_code == country_code)
        .where(IndicatorCatalog.indicator_code == indicator_code)
        .order_by(TimeSeries.date)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return None

    country_name = (
        await session.execute(
            select(CountryProfile.country_name).where(CountryProfile.country_code == country_code)
        )
    ).scalar_one_or_none()

    first = rows[0]
    return IndicatorSeriesOut(
        country_code=country_code,
        country_name=country_name,
        indicator_code=indicator_code,
        indicator_name=first.indicator_name,
        unit=first.unit,
        source=first.source,
        observations=[
            ObservationOut(
                date=r.date,
                value=float(r.value) if r.value is not None else None,
                is_validated=r.is_validated,
            )
            for r in rows
        ],
    )


async def list_country_indicators(
    session: AsyncSession, country_code: str
) -> list[IndicatorSummaryOut]:
    """Latest value per indicator that has data for the country (Postgres DISTINCT ON)."""
    stmt = (
        select(
            IndicatorCatalog.indicator_code,
            IndicatorCatalog.indicator_name,
            IndicatorCatalog.category,
            IndicatorCatalog.unit,
            TimeSeries.date,
            TimeSeries.value,
        )
        .join(IndicatorCatalog, TimeSeries.indicator_id == IndicatorCatalog.id)
        .where(TimeSeries.country_code == country_code)
        .order_by(IndicatorCatalog.indicator_code, TimeSeries.date.desc())
        .distinct(IndicatorCatalog.indicator_code)
    )
    rows = (await session.execute(stmt)).all()
    return [
        IndicatorSummaryOut(
            indicator_code=r.indicator_code,
            indicator_name=r.indicator_name,
            category=r.category,
            unit=r.unit,
            latest_date=r.date,
            latest_value=float(r.value) if r.value is not None else None,
        )
        for r in rows
    ]
