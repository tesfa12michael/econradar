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
    "USA", "CHN", "DEU", "IND", "BRA", "NGA", "ZAF", "KEN", "GHA", "ETH",
    "JAM", "HTI", "DOM", "TTO", "GTM", "HND", "SLV", "CRI", "PAN", "MEX",
)

DEFAULT_WORLD_BANK_INDICATORS: tuple[str, ...] = (
    "NY.GDP.MKTP.KD.ZG",  # GDP growth (annual %)
    "FP.CPI.TOTL.ZG",     # Inflation, consumer prices (annual %)
    "NY.GDP.PCAP.CD",     # GDP per capita (current US$)
    "SL.UEM.TOTL.ZS",     # Unemployment (% of labor force)
    "NE.EXP.GNFS.ZS",     # Exports (% of GDP)
    "NE.IMP.GNFS.ZS",     # Imports (% of GDP)
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
    app_version: str = "0.1.0"   # override with a git SHA in production if desired
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
    google_ai_studio_api_key: str | None = None

    # ── Admin ──
    admin_health_token_hash: str | None = None

    # ── Scheduler ──
    scheduler_enabled: bool = True
    # Cron-ish cadence for the Phase 1 World Bank job (World Bank refreshes weekly).
    world_bank_refresh_cron_day_of_week: str = "mon"
    world_bank_refresh_cron_hour: int = 4
    focus_countries: tuple[str, ...] = Field(default=DEFAULT_FOCUS_COUNTRIES)
    world_bank_indicators: tuple[str, ...] = Field(default=DEFAULT_WORLD_BANK_INDICATORS)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so the environment is parsed once per process."""
    return Settings()


settings = get_settings()
