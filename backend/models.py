"""SQLAlchemy ORM models — a typed mapping over the schema defined in
supabase/migrations/. The database is created and owned by those SQL migrations
(never by ORM `create_all`); these classes exist only for queries and inserts.

Every table in docs/architecture.md's schema outline is mapped: Phase 1 mapped the
ingestion tables, Phase 3 added the AI ones (llm_cache, forecast_cache, embeddings).
"""

from __future__ import annotations

import datetime as dt
import uuid

from pgvector.sqlalchemy import Vector
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Sentence-Transformers all-MiniLM-L6-v2 and Mistral Embed are both reduced to this
# width so one pgvector column serves either provider — see decision #23.
EMBEDDING_DIM = 384

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

    # Measurement metadata (migration 0011). These are what let a caller tell a
    # year-over-year change from a level, a year-end stock from an annual average,
    # and general government from central government — distinctions the indicator
    # name does not reliably carry and that nothing downstream could previously see.
    # Constrained to closed vocabularies in SQL; NULL is legal so a newly ingested
    # indicator is not rejected, and a test fails when one is left unclassified.
    concept: Mapped[str | None] = mapped_column(Text)
    metric_type: Mapped[str | None] = mapped_column(Text)
    transformation: Mapped[str | None] = mapped_column(Text)
    observation_basis: Mapped[str | None] = mapped_column(Text)
    price_basis: Mapped[str | None] = mapped_column(Text)
    coverage_definition: Mapped[str | None] = mapped_column(Text)
    seasonal_adjustment: Mapped[str | None] = mapped_column(Text)
    is_primary_for_concept: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    comparability_notes: Mapped[str | None] = mapped_column(Text)

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


class Anomaly(Base):
    __tablename__ = "anomalies"
    # Detection re-runs after every ingestion, so re-scoring a point must update its
    # row rather than append (see supabase/migrations/0006_anomalies_unique.sql).
    __table_args__ = (
        UniqueConstraint("country_code", "indicator_id", "date", name="anomalies_natural_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, **_UUID_PK)
    country_code: Mapped[str] = mapped_column(String(3))
    indicator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("indicators_catalog.id", ondelete="CASCADE")
    )
    date: Mapped[dt.date] = mapped_column(Date)
    value: Mapped[float | None] = mapped_column(Numeric)
    z_score: Mapped[float | None] = mapped_column(Numeric)
    deviation_type: Mapped[str | None] = mapped_column(Text)
    # Populated in Phase 3 by feature 2.3 — never written by the statistical detector.
    llm_explanation: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), **_NOW)


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


class LlmCache(Base):
    """Every LLM/VLM response, keyed by its inputs (feature 2.5).

    `groundedness_score` is stored beside the text deliberately: a cached narration
    must carry the verdict the verifier reached when it was generated, or a cache
    hit would serve prose whose groundedness nobody has ever checked.
    """

    __tablename__ = "llm_cache"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, **_UUID_PK)
    cache_key: Mapped[str] = mapped_column(Text, unique=True)
    task_type: Mapped[str | None] = mapped_column(Text)
    provider_used: Mapped[str | None] = mapped_column(Text)
    model_used: Mapped[str | None] = mapped_column(Text)
    response_text: Mapped[str | None] = mapped_column(Text)
    groundedness_score: Mapped[float | None] = mapped_column(Numeric)
    token_count: Mapped[int | None] = mapped_column(Integer)
    cache_hit_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), **_NOW)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ForecastCache(Base):
    """A stored quantile forecast (features 1.4 and 2.5).

    Also what keeps the Modal network hop off the request path — the scheduled job
    writes here, and the API only ever reads.
    """

    __tablename__ = "forecast_cache"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, **_UUID_PK)
    cache_key: Mapped[str] = mapped_column(Text, unique=True)
    country_code: Mapped[str] = mapped_column(String(3))
    indicator_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("indicators_catalog.id", ondelete="CASCADE")
    )
    model_used: Mapped[str | None] = mapped_column(Text)
    forecast_horizon: Mapped[int | None] = mapped_column(Integer)
    median_forecast: Mapped[list[float] | None] = mapped_column(ARRAY(Numeric))
    lower_bound: Mapped[list[float] | None] = mapped_column(ARRAY(Numeric))
    upper_bound: Mapped[list[float] | None] = mapped_column(ARRAY(Numeric))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), **_NOW)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Embedding(Base):
    """RAG corpus chunk + its vector (feature 2.2).

    `chunk_text` is the retrieved evidence the answer must cite, so it holds the
    already-formatted numbers rather than a reference to them — the LLM reads what
    is in this column and nothing else.
    """

    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, **_UUID_PK)
    # Stable per-chunk identity so the weekly rebuild upserts rather than
    # duplicating or emptying the corpus (supabase/migrations/0010).
    chunk_key: Mapped[str] = mapped_column(Text, unique=True)
    country_code: Mapped[str | None] = mapped_column(String(3))
    indicator_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("indicators_catalog.id", ondelete="CASCADE")
    )
    chunk_text: Mapped[str] = mapped_column(Text)
    chunk_type: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    date_range_start: Mapped[dt.date | None] = mapped_column(Date)
    date_range_end: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), **_NOW)
