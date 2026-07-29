"""Read-side data access for the API. Thin, typed queries over the ORM so routers
stay declarative and this layer can be exercised directly in tests.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Anomaly, CountryProfile, DataSource, IndicatorCatalog, TimeSeries
from schemas import (
    AnomalyOut,
    CountryOut,
    IndicatorOptionOut,
    IndicatorSeriesOut,
    IndicatorSummaryOut,
    MapDataOut,
    MapPointOut,
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


async def count_observations(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(TimeSeries))).scalar_one()


async def count_anomalies(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(Anomaly))).scalar_one()


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


async def list_indicator_options(session: AsyncSession) -> list[IndicatorOptionOut]:
    """Indicators that actually have data, with how many countries each covers.

    The map's indicator picker uses the country count to lead with the series that
    will render a full choropleth rather than a nearly-empty one.
    """
    stmt = (
        select(
            IndicatorCatalog.indicator_code,
            IndicatorCatalog.indicator_name,
            IndicatorCatalog.category,
            IndicatorCatalog.unit,
            IndicatorCatalog.frequency,
            DataSource.name.label("source"),
            func.count(func.distinct(TimeSeries.country_code)).label("country_count"),
        )
        .join(TimeSeries, TimeSeries.indicator_id == IndicatorCatalog.id)
        .join(DataSource, IndicatorCatalog.source_id == DataSource.id)
        .group_by(
            IndicatorCatalog.indicator_code,
            IndicatorCatalog.indicator_name,
            IndicatorCatalog.category,
            IndicatorCatalog.unit,
            IndicatorCatalog.frequency,
            DataSource.name,
        )
        .order_by(func.count(func.distinct(TimeSeries.country_code)).desc())
    )
    return [
        IndicatorOptionOut(
            indicator_code=r.indicator_code,
            indicator_name=r.indicator_name,
            category=r.category,
            unit=r.unit,
            frequency=r.frequency,
            source=r.source,
            country_count=r.country_count,
        )
        for r in (await session.execute(stmt)).all()
    ]


async def get_map_data(session: AsyncSession, indicator_code: str) -> MapDataOut | None:
    """Latest value per country for one indicator, plus whether it has an anomaly.

    Countries with no data are simply absent here; the frontend renders them in the
    no-data colour rather than as zero.
    """
    latest = (
        select(
            TimeSeries.country_code,
            TimeSeries.date,
            TimeSeries.value,
            IndicatorCatalog.indicator_name,
            IndicatorCatalog.unit,
            DataSource.name.label("source"),
        )
        .join(IndicatorCatalog, TimeSeries.indicator_id == IndicatorCatalog.id)
        .join(DataSource, TimeSeries.source_id == DataSource.id)
        .where(IndicatorCatalog.indicator_code == indicator_code)
        .where(TimeSeries.value.is_not(None))
        .order_by(TimeSeries.country_code, TimeSeries.date.desc())
        .distinct(TimeSeries.country_code)
    )
    rows = (await session.execute(latest)).all()
    if not rows:
        return None

    # Flag only countries whose *displayed* observation is the anomalous one. Asking
    # "has this country ever been anomalous" marks ~205 of 214 across sixty years of
    # history, which makes the marker meaningless; this way it says something true
    # about the number on screen.
    latest_dates = {r.country_code: r.date for r in rows}
    flagged = {
        code
        for code, date in (
            await session.execute(
                select(Anomaly.country_code, Anomaly.date)
                .join(IndicatorCatalog, Anomaly.indicator_id == IndicatorCatalog.id)
                .where(IndicatorCatalog.indicator_code == indicator_code)
            )
        ).all()
        if latest_dates.get(code) == date
    }

    names = dict(
        (await session.execute(select(CountryProfile.country_code, CountryProfile.country_name)))
        .tuples()
        .all()
    )

    first = rows[0]
    return MapDataOut(
        indicator_code=indicator_code,
        indicator_name=first.indicator_name,
        unit=first.unit,
        source=first.source,
        points=[
            MapPointOut(
                country_code=r.country_code,
                country_name=names.get(r.country_code),
                value=float(r.value),
                date=r.date,
                has_anomaly=r.country_code in flagged,
            )
            for r in rows
        ],
    )


async def list_anomalies(
    session: AsyncSession,
    country_code: str | None = None,
    indicator_code: str | None = None,
    limit: int = 100,
) -> list[AnomalyOut]:
    stmt = (
        select(
            Anomaly.country_code,
            Anomaly.date,
            Anomaly.value,
            Anomaly.z_score,
            Anomaly.deviation_type,
            Anomaly.detected_at,
            IndicatorCatalog.indicator_code,
            IndicatorCatalog.indicator_name,
            CountryProfile.country_name,
        )
        .join(IndicatorCatalog, Anomaly.indicator_id == IndicatorCatalog.id)
        .outerjoin(CountryProfile, CountryProfile.country_code == Anomaly.country_code)
        .order_by(Anomaly.date.desc())
        .limit(limit)
    )
    if country_code:
        stmt = stmt.where(Anomaly.country_code == country_code)
    if indicator_code:
        stmt = stmt.where(IndicatorCatalog.indicator_code == indicator_code)

    return [
        AnomalyOut(
            country_code=r.country_code,
            country_name=r.country_name,
            indicator_code=r.indicator_code,
            indicator_name=r.indicator_name,
            date=r.date,
            value=float(r.value) if r.value is not None else None,
            z_score=float(r.z_score) if r.z_score is not None else None,
            deviation_type=r.deviation_type,
            detected_at=r.detected_at,
        )
        for r in (await session.execute(stmt)).all()
    ]


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
