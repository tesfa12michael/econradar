"""Pydantic models: the shared inter-layer `TimeSeriesRecord` plus API I/O schemas.

`TimeSeriesRecord` is the single normalized shape every connector must emit
(architecture.md § Data Ingestion Layer) — provider-specific payloads converge here
before anything touches the database.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, field_validator


class TimeSeriesRecord(BaseModel):
    """One normalized observation. The contract between connectors and storage."""

    model_config = ConfigDict(frozen=True)

    country_code: str  # ISO 3166-1 alpha-3
    indicator_code: str  # source-native code, e.g. FP.CPI.TOTL.ZG
    source_name: str  # data_sources.name, e.g. world_bank
    date: dt.date
    value: float
    unit: str | None = None
    is_validated: bool = False

    @field_validator("country_code")
    @classmethod
    def _iso3(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 3 or not v.isalpha():
            raise ValueError(f"country_code must be ISO-3 alpha, got {v!r}")
        return v

    @field_validator("indicator_code", "source_name")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


# ── API response models ──────────────────────────────────────


class CountryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    country_code: str
    country_name: str
    region: str | None = None
    income_classification: str | None = None
    imf_classification: str | None = None
    flag_emoji: str | None = None


class ObservationOut(BaseModel):
    date: dt.date
    value: float | None
    is_validated: bool = False


class IndicatorSeriesOut(BaseModel):
    """A single country+indicator historical series with source attribution."""

    country_code: str
    country_name: str | None = None
    indicator_code: str
    indicator_name: str | None = None
    unit: str | None = None
    source: str
    observations: list[ObservationOut]


class IndicatorSummaryOut(BaseModel):
    """Latest value for one indicator available for a country (catalog view)."""

    indicator_code: str
    indicator_name: str
    category: str | None = None
    unit: str | None = None
    latest_date: dt.date | None = None
    latest_value: float | None = None


class HealthOut(BaseModel):
    status: str
    environment: str
    version: str
    database: str  # connected | unavailable | not_configured
    scheduler: str  # running | stopped | disabled


class SourceStatusOut(BaseModel):
    name: str
    is_active: bool
    last_successful_run: dt.datetime | None = None


class StatusOut(BaseModel):
    """Sanitized public status (design-system Flow 3). No internal detail."""

    status: str
    environment: str
    countries_tracked: int
    indicators_tracked: int
    sources: list[SourceStatusOut]
    groundedness_verification: str = "active"
