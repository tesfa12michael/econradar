"""Application configuration, loaded from the environment (and an optional .env).

Every field is optional with a safe default so importing this module never fails —
tests, the /health endpoint, and a DB-less local boot all work without secrets.
Field names map case-insensitively to the env vars in docs/architecture.md
(e.g. DATABASE_URL -> database_url).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The curated focus set for the Phase 1 scheduled World Bank job: majors plus the
# data-sparse regions EconRadar targets (Caribbean, Central America, Sub-Saharan
# Africa). Kept small so free-tier ingestion stays light; broadened in Phase 2.
DEFAULT_FOCUS_COUNTRIES: tuple[str, ...] = (
    "USA",
    "CHN",
    "DEU",
    "IND",
    "BRA",
    "NGA",
    "ZAF",
    "KEN",
    "GHA",
    "ETH",
    "JAM",
    "HTI",
    "DOM",
    "TTO",
    "GTM",
    "HND",
    "SLV",
    "CRI",
    "PAN",
    "MEX",
)

DEFAULT_WORLD_BANK_INDICATORS: tuple[str, ...] = (
    "NY.GDP.MKTP.KD.ZG",  # GDP growth (annual %)
    "FP.CPI.TOTL.ZG",  # Inflation, consumer prices (annual %)
    "NY.GDP.PCAP.CD",  # GDP per capita (current US$)
    "SL.UEM.TOTL.ZS",  # Unemployment (% of labor force)
    "NE.EXP.GNFS.ZS",  # Exports (% of GDP)
    "NE.IMP.GNFS.ZS",  # Imports (% of GDP)
    "GC.DOD.TOTL.GD.ZS",  # Central government debt (% of GDP)
    "BN.CAB.XOKA.GD.ZS",  # Current account balance (% of GDP)
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Core app ──
    environment: str = "development"
    app_version: str = "0.1.0"  # override with a git SHA in production if desired
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    # Comma-separated origins allowed by CORS (the Vercel URL in production).
    cors_origins: str = "http://localhost:3000"

    # ── Supabase / database ──
    database_url: str | None = None
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None

    # ── Data source keys (World Bank is keyless; rest arrive Phase 2+) ──
    world_bank_api_key: str | None = None
    fred_api_key: str | None = None
    bis_api_key: str | None = None

    # ── LLM / VLM providers (Phase 3) ──
    mistral_api_key: str | None = None
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    # Google renamed Vertex AI to "Agent Platform"; its keys authenticate against
    # aiplatform.googleapis.com and are *rejected* by the AI Studio host
    # (generativelanguage.googleapis.com returns 403). Both names are accepted so an
    # older .env keeps working — read them through `google_api_key`, never directly.
    google_agent_platform_api_key: str | None = None
    google_ai_studio_api_key: str | None = None
    # Qwen3-VL served direct from DashScope rather than through OpenRouter, whose
    # free Qwen3-VL slug was withdrawn (decision #28). Transport only — the VLM
    # fallback order in docs/architecture.md #9 is unchanged.
    qwen_api_key: str | None = None

    # ── Admin ──
    admin_health_token_hash: str | None = None

    # ── Scheduler ──
    scheduler_enabled: bool = True
    # Cron-ish cadence for the Phase 1 World Bank job (World Bank refreshes weekly).
    world_bank_refresh_cron_day_of_week: str = "mon"
    world_bank_refresh_cron_hour: int = 4
    focus_countries: tuple[str, ...] = Field(default=DEFAULT_FOCUS_COUNTRIES)
    world_bank_indicators: tuple[str, ...] = Field(default=DEFAULT_WORLD_BANK_INDICATORS)
    imf_indicators: tuple[str, ...] = Field(default=())

    # World Bank ingestion scope. "all" pulls every country the API knows, which is what
    # the world map needs to look complete; aggregates and regions come back too and are
    # rejected by the ISO-3 check. Set to "focus" to fall back to focus_countries.
    world_bank_country_scope: str = "all"

    # Global Economic Monitor is monthly only when given an explicit range in the World
    # Bank's own YYYYMnn spelling; without one it silently returns annual aggregates.
    gem_start_period: str = "2015M01"
    gem_end_period: str = "2026M12"

    # ── Anomaly detection (feature 1.8) ──
    # Threshold is configurable, not hardcoded — an acceptance criterion.
    anomaly_z_threshold: float = 2.0
    anomaly_window: int = 12
    # A rolling Z-score needs enough history to mean anything; below this a series is
    # left unflagged rather than flagged on noise.
    anomaly_min_observations: int = 8

    # ── Forecasting (feature 1.4) ──
    # Modal hosts Chronos-2 and TimesFM (decision #21); StatsForecast runs here
    # (decision #22), which is what makes a Modal outage survivable.
    modal_enabled: bool = True
    modal_app_name: str = "econradar-forecast"
    # A cold serverless GPU can take a while to answer; past this the cascade moves on
    # rather than holding a scheduled job open.
    modal_timeout_seconds: float = 420.0

    # Horizon in *periods of the series' own frequency*, not a fixed number of months.
    # A 12-month horizon on an annual series is a single step, which is not a forecast;
    # 12 years ahead on one is not a defensible one either. Set per frequency instead.
    forecast_horizon_monthly: int = 12
    forecast_horizon_quarterly: int = 8
    forecast_horizon_annual: int = 5
    # Below this a series is refused rather than forecast — features.md 1.4's
    # "a series too short for meaningful forecasting" edge case.
    forecast_min_observations: int = 16
    # Chronos-2 and TimesFM both cap their context; more history than this is trimmed
    # to the most recent points rather than sent and silently truncated upstream.
    forecast_max_context: int = 512
    forecast_cache_ttl_days: int = 30
    # Countries the scheduled forecast job covers, most-viewed first. Forecasting every
    # (country, indicator) pair would be ~3,200 GPU calls a week for series nobody opens.
    forecast_countries: tuple[str, ...] = Field(default=DEFAULT_FOCUS_COUNTRIES)

    # ── LLM / VLM (features 1.5, 2.1, 2.2, 2.3) ──
    llm_enabled: bool = True
    # Model per provider. Names change on free tiers, so they are configuration.
    mistral_model: str = "mistral-small-latest"
    groq_model: str = "llama-3.3-70b-versatile"
    # llama-3.3-70b-instruct:free was withdrawn from OpenRouter's free tier — the API
    # answers 404 with "use the paid slug instead". Free slugs churn; that is exactly
    # why these are configuration and not constants.
    openrouter_model: str = "openai/gpt-oss-20b:free"
    gemini_model: str = "gemini-3.6-flash"
    qwen_vlm_model: str = "qwen3-vl-plus"
    llm_timeout_seconds: float = 45.0
    llm_max_tokens: int = 700
    # Gemini 3.x thinks before answering, and the thoughts are charged against
    # maxOutputTokens. Sharing the 700-token budget would let thinking swallow the
    # response whole and return an empty candidate, so Gemini gets its own ceiling.
    # Measured on this workload: thinkingLevel "low" spends ~350 thinking tokens
    # against ~1,950 at "high" and ~2,550 unset, and 2048 total proved marginal once
    # a chart image and a full data block were in the request — it intermittently
    # tripped the MAX_TOKENS guard below. 4096 clears the observed worst case while
    # still bounding a runaway.
    gemini_max_output_tokens: int = 4096
    gemini_thinking_level: str = "low"
    # Low but not zero: narration must stay close to the supplied numbers, and a
    # temperature of 0 makes every country's prose read identically.
    llm_temperature: float = 0.2
    narration_cache_ttl_hours: int = 24
    vlm_cache_ttl_days: int = 7
    rag_cache_ttl_hours: int = 24

    # Groundedness (decision #8). A narration whose score falls below this is not
    # served — the fabricated number is the failure, so the response is.
    groundedness_min_score: float = 1.0
    # Rounding slack when matching a narrated number against the context: "3.4%" must
    # match a stored 3.42, or the verifier fails honest prose. Relative tolerance.
    groundedness_tolerance: float = 0.005

    # ── RAG (feature 2.2) ──
    rag_top_k: int = 8
    # Retrieval below this cosine similarity is treated as "nothing relevant found",
    # which triggers the insufficient-data refusal rather than a grounded-looking guess.
    rag_min_similarity: float = 0.25
    rag_context_turns: int = 4
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    @property
    def google_api_key(self) -> str | None:
        """The Gemini key, under whichever of the two names it was supplied."""
        return self.google_agent_platform_api_key or self.google_ai_studio_api_key

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def world_bank_countries(self) -> list[str] | str:
        """Country selector passed to the World Bank connectors."""
        if self.world_bank_country_scope.strip().lower() == "all":
            return "all"
        return list(self.focus_countries)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so the environment is parsed once per process."""
    return Settings()


settings = get_settings()
