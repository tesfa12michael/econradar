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
    date: dt.date  # first day of the observation period (see connectors/dates.py)
    value: float
    unit: str | None = None
    frequency: str | None = None  # annual | quarterly | monthly | daily
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


class AnomalyOut(BaseModel):
    """A statistically flagged observation. Magnitude and timing only — the grounded
    narrative explanation arrives in Phase 3 (feature 2.3)."""

    country_code: str
    country_name: str | None = None
    indicator_code: str
    indicator_name: str | None = None
    date: dt.date
    value: float | None = None
    z_score: float | None = None
    deviation_type: str | None = None  # spike | drop
    detected_at: dt.datetime | None = None


class MapPointOut(BaseModel):
    """One country's latest value for a chosen indicator, for the choropleth.

    `value` is None for a country with no data — the map must render that distinctly
    rather than as a false zero (features.md 1.6).
    """

    country_code: str
    country_name: str | None = None
    value: float | None = None
    date: dt.date | None = None
    has_anomaly: bool = False


class MapDataOut(BaseModel):
    indicator_code: str
    indicator_name: str | None = None
    unit: str | None = None
    source: str | None = None
    points: list[MapPointOut]


class IndicatorOptionOut(BaseModel):
    """A selectable indicator for the map/profile pickers."""

    indicator_code: str
    indicator_name: str
    category: str | None = None
    unit: str | None = None
    frequency: str | None = None
    source: str
    country_count: int = 0


class ForecastPointOut(BaseModel):
    """One projected period. `lower`/`upper` are the p10/p90 bounds."""

    date: dt.date
    median: float
    lower: float
    upper: float


class ForecastOut(BaseModel):
    """A quantile forecast (feature 1.4).

    `model_used` is always reported, never inferred by the client: which model in
    the Chronos-2 -> TimesFM -> StatsForecast cascade produced a number is part of
    what the number means, and it is what makes the fallback observable.
    """

    country_code: str
    indicator_code: str
    indicator_name: str | None = None
    unit: str | None = None
    frequency: str | None = None
    model_used: str
    horizon: int
    points: list[ForecastPointOut]
    cached: bool = False
    generated_at: dt.datetime | None = None


class NarrationOut(BaseModel):
    """Grounded commentary on one series (feature 1.5).

    `groundedness_score` describes *this text*: it is the verifier's verdict on the
    string being returned, recorded when the text was generated and carried through
    the cache with it. A cached narration therefore never arrives unverified.
    """

    country_code: str
    indicator_code: str
    text: str
    provider: str
    model: str
    groundedness_score: float | None = None
    cached: bool = False


class ChartInterpretationOut(BaseModel):
    """A vision model's reading of the rendered chart (feature 2.1)."""

    country_code: str
    indicator_code: str
    text: str
    provider: str
    model: str
    groundedness_score: float | None = None
    cached: bool = False


class AnomalyExplanationOut(BaseModel):
    """A grounded explanation of one flagged observation (feature 2.3).

    `explanation` is nullable: when no provider returns a grounded response the
    anomaly is still returned, with its statistics and without prose. A flagged
    observation with no explanation is a true state of the system; an invented
    explanation would not be.
    """

    country_code: str
    indicator_code: str
    date: dt.date
    value: float | None = None
    z_score: float | None = None
    deviation_type: str | None = None
    explanation: str | None = None
    cached: bool = False


class ChatTurn(BaseModel):
    role: str  # user | assistant
    content: str


class ChatRequest(BaseModel):
    """One question plus the recent conversation (feature 2.2).

    History is supplied by the client and trimmed server-side to the documented
    four turns — it resolves pronouns and follow-ups, and is explicitly not
    evidence: the prompt says so, and only retrieved chunks are verified against.
    """

    question: str
    history: list[ChatTurn] = []


class CitationOut(BaseModel):
    """A retrieved evidence card, numbered to match the [n] markers in the answer."""

    index: int
    country_code: str | None = None
    country_name: str | None = None
    indicator_code: str | None = None
    indicator_name: str | None = None
    chunk_type: str | None = None
    similarity: float = 0.0


class ChatResponse(BaseModel):
    """A verified answer, or an empty one with the reason it did not survive.

    `answer` is empty whenever `grounded` is false. There is no partial-credit
    state: an answer that failed verification is not returned in any form.
    """

    answer: str
    citations: list[CitationOut] = []
    grounded: bool = False
    groundedness_score: float | None = None
    provider: str | None = None
    cached: bool = False
    error: str | None = None


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
    observations_tracked: int = 0
    anomalies_flagged: int = 0
    sources: list[SourceStatusOut]
    groundedness_verification: str = "active"
