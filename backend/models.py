"""SQLAlchemy ORM models — a typed mapping over the schema defined in
supabase/migrations/. The database is created and owned by those SQL migrations
(never by ORM `create_all`); these classes exist only for queries and inserts.

Only the tables Phase 1 code reads or writes are mapped. The remaining tables
(anomalies, llm_cache, forecast_cache, embeddings) exist in SQL and are mapped
when their features land (Phase 3).
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

_UUID_PK = {"primary_key": True, "server_default": text("gen_random_uuid()")}
_NOW = {"server_default": text("now()")}


class Base(DeclarativeBase):
    pass


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, **_UUID_PK)
    name: Mapped[str] = mapped_column(Text, unique=True)
    base_url: Mapped[str] = mapped_column(Text)
    last_successful_run: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class CountryProfile(Base):
    __tablename__ = "country_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, **_UUID_PK)
    country_code: Mapped[str] = mapped_column(String(3), unique=True)
    country_name: Mapped[str] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    income_classification: Mapped[str | None] = mapped_column(Text)
    imf_classification: Mapped[str | None] = mapped_column(Text)
    population_bracket: Mapped[str | None] = mapped_column(Text)
    flag_emoji: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), **_NOW)


class IndicatorCatalog(Base):
    __tablename__ = "indicators_catalog"
    __table_args__ = (UniqueConstraint("source_id", "indicator_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, **_UUID_PK)
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE")
    )
    indicator_code: Mapped[str] = mapped_column(Text)
    indicator_name: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)

    source: Mapped[DataSource] = relationship(lazy="raise")


class TimeSeries(Base):
    __tablename__ = "time_series"
    # Composite PK (id, date) because the table is RANGE-partitioned on date; the
    # natural key backs upsert + the documented (country_code, indicator_id, date) lookup.
    __table_args__ = (
        UniqueConstraint("country_code", "indicator_id", "date", name="time_series_natural_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    country_code: Mapped[str] = mapped_column(String(3))
    indicator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("indicators_catalog.id", ondelete="CASCADE")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE")
    )
    value: Mapped[float | None] = mapped_column(Numeric)
    is_validated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    ingested_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), **_NOW)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, **_UUID_PK)
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("data_sources.id", ondelete="CASCADE")
    )
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), **_NOW)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    records_fetched: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    records_inserted: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    records_failed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'running'"))


class EtlError(Base):
    __tablename__ = "etl_errors"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, **_UUID_PK)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("pipeline_runs.id", ondelete="CASCADE")
    )
    raw_record: Mapped[dict | None] = mapped_column(JSONB)
    error_type: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), **_NOW)
