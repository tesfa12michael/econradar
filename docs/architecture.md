<!-- filename: agent_docs/architecture.md -->
# Architecture

## Confirmed Tech Stack — Layer by Layer

| Layer | Tool | Version | Rationale |
|---|---|---|---|
| Frontend Framework | Next.js | 15 (App Router) | The confident full-stack choice for an AI-adjacent product — server components, streaming, and a clean split from the FastAPI backend. |
| Frontend Language | TypeScript | 5.x | Paired with FastAPI's Pydantic models and Zod on the client for end-to-end type safety. |
| UI Component Library | shadcn/ui + Tailwind CSS | v4 / latest | Zero runtime overhead, copy-paste primitives, no vendor lock-in — needed for a dashboard that must look distinctive, not like a template. |
| Map Visualization | MapLibre GL JS + deck.gl | 4.x / 9.x | Open-source Mapbox fork (no token, no cost) plus WebGL-level rendering for 195+ country polygons with live data overlays. |
| Chart Library | Recharts + Plotly (server-side) | latest | Recharts for interactive frontend charts; Plotly for headless server-side PNG rendering that feeds the VLM pipeline. |
| Backend Framework | FastAPI | 0.115.x | Handles AI inference, background jobs, and long DB queries natively with async support. |
| Backend Language | Python | 3.12 | Required for Chronos-2, HuggingFace transformers, pandas — no compromise here. |
| Task Scheduler | APScheduler (AsyncIOScheduler) | 3.x | Non-blocking, FastAPI-native; persisted via `SQLAlchemyJobStore` against Supabase so jobs survive Render restarts. |
| Primary Database | Supabase PostgreSQL | 15 | Real managed Postgres on a genuinely usable free tier (500MB DB, pgvector included, no sandbox limitations). |
| Time-Series Storage | Native PostgreSQL partitioning + `pg_partman` | built-in | TimescaleDB is unavailable on new Supabase Postgres 17+ projects (licensing conflict). Native range partitioning delivers the core time-series performance benefit at zero licensing risk. |
| Vector Store (RAG) | Supabase pgvector | 0.7+ | Free on all Supabase plans; avoids standing up a separate vector service and its cost/failure surface. |
| Forecasting — Primary | Chronos-2 (amazon/chronos-2) | latest, "mini" default | State-of-the-art zero-shot accuracy; supports CPU inference, so it runs free on Render with no GPU. |
| Forecasting — Fallback 1 | TimesFM (google/timesfm) | latest | Google's production-validated TSFM; activates if Chronos-2 fails or is too slow for a given series. |
| Forecasting — Fallback 2 | Nixtla StatsForecast | latest | Pure Python, no model weights, ARIMA/ETS baseline — the guaranteed last resort. |
| LLM — Primary (Narration) | Mistral API | latest | Most generous permanent free token volume among viable providers. |
| LLM — Speed Layer (Q&A) | Groq (Llama 3.3 70B) | latest | Fastest free inference (LPU hardware) for latency-sensitive RAG responses. |
| VLM — Primary | Google AI Studio (Gemini Flash) | 2.5 | Permanent free tier, native vision, no credit card — feeds the chart-to-narrative pipeline. |
| VLM — Fallback | Qwen3-VL via OpenRouter | latest | Best open-weight VLM as of 2026, routed through OpenRouter's unified gateway. |
| LLM Gateway / Fallback | OpenRouter | latest | 30+ free models behind one OpenAI-compatible API — the final fallback when primary providers rate-limit. |
| Embeddings (RAG) | Mistral Embed / Sentence-Transformers | latest | Mistral Embed for the cloud path; self-hosted `all-MiniLM-L6-v2` as a zero-API-call fallback. |
| Frontend Hosting | Vercel | Free Tier | Next.js native, custom subdomain, zero config. |
| Backend Hosting | Render | Free Tier | Python runtime, persistent disk, free Postgres connection; hosts FastAPI + APScheduler together. |
| Keep-Alive | UptimeRobot | Free Tier | Pings Render and Supabase every 5 days to prevent free-tier sleep. |
| Repo / CI | GitHub + GitHub Actions | Free | Open source, version control, lint/test CI. |

### Alternatives Considered and Rejected

| Tool | Rejected Because |
|---|---|
| Celery + Redis | Needs a separate Redis instance — real cost or free-tier complexity APScheduler + Supabase jobstore avoids entirely. |
| Pinecone / Weaviate / Qdrant | A dedicated vector service is more expensive and adds a failure point Supabase + pgvector eliminates. |
| Leaflet (standalone) | Can't handle WebGL-level rendering for 195+ live country polygons the way deck.gl can. |
| Mapbox GL JS | Requires a paid token above free limits; MapLibre is the identical open-source fork at zero cost. |
| Fly.io / Railway | No real free tier remains for new users in 2026; Render is the last host with a genuine free Python runtime. |

## System Architecture

### Description

Five logical layers communicate through defined interfaces only:

1. **Data Ingestion Layer** — five connector classes (World Bank, IMF, FRED, BIS, WB DataBank), all inheriting `BaseDataSourceConnector`. Each handles its own pagination, rate limiting, and schema normalization. APScheduler triggers each on its configured cadence; all output normalizes to a shared `TimeSeriesRecord` Pydantic model before touching the database.
2. **Storage Layer** — Supabase PostgreSQL is the single source of truth for structured data (time series, metadata, anomalies, pipeline logs, LLM cache) and vector data (RAG embeddings via pgvector). No secondary databases.
3. **Intelligence Layer** — three co-equal AI subsystems behind service interfaces: `ForecastingService` (Chronos-2 → TimesFM → StatsForecast), `LLMService` (Mistral → Groq → OpenRouter, routed by task type), `VLMService` (Gemini Flash → Qwen3-VL via OpenRouter).
4. **API Layer** — FastAPI exposes a clean REST API to the Next.js frontend. All AI service calls are async; forecasts and narrations are cached in Supabase before returning to the client.
5. **Presentation Layer** — Next.js 15 App Router: server components for SEO/initial load, client components for the interactive map, charts, and RAG chat. MapLibre + deck.gl handle the map; Recharts handles time-series visualization.

### ASCII Diagram

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                         DATA SOURCES (External)                             ║
║  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐  ║
║  │  World Bank │ │  IMF SDMX   │ │    FRED      │ │  BIS + WB DataBank  │  ║
║  │  REST/JSON  │ │  2.1 / 3.0  │ │   REST API   │ │   REST / JSON       │  ║
║  └──────┬──────┘ └──────┬──────┘ └──────┬───────┘ └──────────┬──────────┘  ║
╚═════════╪══════════════╪═══════════════╪═════════════════════╪═════════════╝
          │              │               │                     │
          └──────────────┴───────────────┴─────────────────────┘
                                         │
                    ╔════════════════════╪═════════════════════╗
                    ║    BACKEND (Render — FastAPI + Python)   ║
                    ║                    ▼                     ║
                    ║  ┌─────────────────────────────────────┐ ║
                    ║  │  ETL Layer (BaseDataSourceConnector) │ ║
                    ║  │  • Schema normalization              │ ║
                    ║  │  • Validation + error logging        │ ║
                    ║  │  • APScheduler (persisted to DB)     │ ║
                    ║  └────────────────┬────────────────────┘ ║
                    ║                   │                      ║
                    ║                   ▼                      ║
                    ║  ╔════════════════════════════════════╗  ║
                    ║  ║  SUPABASE POSTGRESQL               ║  ║
                    ║  ║  ┌──────────────────────────────┐  ║  ║
                    ║  ║  │ time_series (partitioned)    │  ║  ║
                    ║  ║  │ indicators_catalog           │  ║  ║
                    ║  ║  │ data_sources                 │  ║  ║
                    ║  ║  │ country_profiles              │  ║  ║
                    ║  ║  │ anomalies                    │  ║  ║
                    ║  ║  │ pipeline_runs + etl_errors   │  ║  ║
                    ║  ║  │ llm_cache / forecast_cache   │  ║  ║
                    ║  ║  │ embeddings (pgvector / HNSW) │  ║  ║
                    ║  ║  └──────────────────────────────┘  ║  ║
                    ║  ╚═════════════════════════════════════╝  ║
                    ║          │             │            │     ║
                    ║          ▼             ▼            ▼     ║
                    ║  ┌──────────┐ ┌───────────┐ ┌──────────┐ ║
                    ║  │Forecast  │ │ RAG /     │ │  LLM /   │ ║
                    ║  │Service   │ │ Embedding │ │  VLM     │ ║
                    ║  │Chronos-2 │ │ Service   │ │ Service  │ ║
                    ║  │→TimesFM  │ │ pgvector  │ │ Mistral  │ ║
                    ║  │→Stats    │ │ hybrid    │ │ →Groq    │ ║
                    ║  │Forecast  │ │ retrieval │ │ →OR      │ ║
                    ║  └────┬─────┘ └─────┬─────┘ └────┬─────┘ ║
                    ║       └─────────────┴────────────┘      ║
                    ║                    │                     ║
                    ║                    ▼                     ║
                    ║  ┌─────────────────────────────────────┐ ║
                    ║  │       FastAPI REST API Layer         │ ║
                    ║  │  /api/v1/countries                  │ ║
                    ║  │  /api/v1/indicators/{country}       │ ║
                    ║  │  /api/v1/forecast/{country}/{ind}   │ ║
                    ║  │  /api/v1/narrate/{country}/{ind}    │ ║
                    ║  │  /api/v1/vlm-interpret/{country}    │ ║
                    ║  │  /api/v1/chat (RAG Q&A)             │ ║
                    ║  │  /api/v1/anomalies                  │ ║
                    ║  │  /status (public, sanitized)        │ ║
                    ║  │  /admin/health (private, token-gated)│ ║
                    ║  └────────────────────┬────────────────┘ ║
                    ╚═══════════════════════╪═════════════════╝
                                           │
                    ╔══════════════════════╪══════════════════╗
                    ║   FRONTEND (Vercel — Next.js 15)        ║
                    ║                      ▼                  ║
                    ║  ┌─────────────────────────────────────┐ ║
                    ║  │  / (World Map Dashboard)            │ ║
                    ║  │  MapLibre GL JS + deck.gl           │ ║
                    ║  │  Choropleth + Anomaly Overlays      │ ║
                    ║  └─────────────────────────────────────┘ ║
                    ║  ┌─────────────────────────────────────┐ ║
                    ║  │  /country/[code] (Profile Page)     │ ║
                    ║  │  Recharts time-series + forecast    │ ║
                    ║  │  LLM narration panel                │ ║
                    ║  │  VLM chart interpretation panel     │ ║
                    ║  └─────────────────────────────────────┘ ║
                    ║  ┌─────────────────────────────────────┐ ║
                    ║  │  /chat (RAG Q&A Interface)          │ ║
                    ║  │  shadcn/ui Chat + Citation cards    │ ║
                    ║  └─────────────────────────────────────┘ ║
                    ╚═════════════════════════════════════════╝

                    ╔═════════════════════════════════════════╗
                    ║   EXTERNAL AI SERVICES                  ║
                    ║  ┌──────────┐ ┌─────────┐ ┌─────────┐  ║
                    ║  │ Mistral  │ │  Groq   │ │OpenRtr  │  ║
                    ║  │ (narrat.)│ │ (Q&A)   │ │(fallbk) │  ║
                    ║  └──────────┘ └─────────┘ └─────────┘  ║
                    ║  ┌──────────────────────────────────┐   ║
                    ║  │ Google AI Studio (Gemini Flash)  │   ║
                    ║  │ VLM — chart image interpretation │   ║
                    ║  └──────────────────────────────────┘   ║
                    ╚═════════════════════════════════════════╝
```

## Primary Data Flow — "User Loads Country Profile Page"

```
Step 1  USER requests /country/NGA?indicator=inflation

Step 2  NEXT.JS server component initiates parallel fetch calls to FastAPI:
        → GET /api/v1/indicators/NGA?code=FP.CPI.TOTL.ZG
        → GET /api/v1/forecast/NGA?indicator=FP.CPI.TOTL.ZG&horizon=12
        → GET /api/v1/narrate/NGA?indicator=FP.CPI.TOTL.ZG
        → GET /api/v1/anomalies?country=NGA&indicator=FP.CPI.TOTL.ZG

Step 3  FASTAPI — /indicators handler:
        → Queries Supabase time_series table (partitioned by country_code + year)
        → Joins country_profiles for name/region/classification metadata
        → Returns historical data array + source attribution metadata

Step 4  FASTAPI — /forecast handler:
        → Checks forecast_cache: key = (NGA, FP.CPI.TOTL.ZG, current_month, chronos-2)
        → CACHE HIT → returns stored quantile forecast array instantly
        → CACHE MISS →
             a. Pulls last 60 data points from time_series
             b. Passes to ForecastingService.predict()
             c. ForecastingService tries Chronos-2 (CPU inference)
             d. If Chronos-2 fails or times out → TimesFM
             e. If TimesFM fails → Nixtla StatsForecast
             f. Returns {median, p10, p90} quantile arrays for 12 months
             g. Stores result in forecast_cache with 30-day TTL
             h. Returns to client

Step 5  FASTAPI — /narrate handler:
        → Checks llm_cache: key = (NGA, FP.CPI.TOTL.ZG, current_month, narration)
        → CACHE HIT → returns stored narration string
        → CACHE MISS →
             a. Assembles structured context: last 4 data points + forecast p50 + anomaly flags
             b. Renders Jinja2 prompt template with injected numbers
             c. Calls LLMService.narrate() → Mistral primary
             d. If Mistral rate-limits → Groq → OpenRouter
             e. Runs groundedness verifier: extracts all numbers from LLM response,
                checks each against context object — flags any hallucinated values
             f. Stores result + groundedness score in llm_cache (24h TTL)
             g. Returns narration string

Step 6  FASTAPI — /anomalies handler:
        → Queries anomalies table for NGA + indicator
        → Returns flagged points with z_score, magnitude, and stored LLM explanation

Step 7  FASTAPI — VLM pipeline (triggered client-side after chart render):
        → Frontend sends GET /api/v1/vlm-interpret/NGA?indicator=...
        → Backend checks llm_cache (task_type = vlm_interpretation, 7-day TTL)
        → CACHE MISS →
             a. Fetches last 36 data points + forecast array
             b. Renders chart to PNG using Plotly (server-side, headless)
             c. Encodes PNG as base64
             d. Calls VLMService.interpret(image_b64, context_metadata)
             e. VLMService sends to Gemini Flash (Google AI Studio)
             f. If Gemini rate-limits → Qwen3-VL via OpenRouter
             g. Stores VLM interpretation in llm_cache
             h. Returns structured interpretation text

Step 8  NEXT.JS assembles the page:
        → Recharts renders interactive historical + forecast overlay chart
        → LLM narration panel displays below chart
        → VLM interpretation panel displays as "AI Chart Analysis" section
        → Anomaly badges render on chart and in sidebar
        → Data source attribution links render in footer

Step 9  All responses cached at the Supabase layer — next request for the same
        country/indicator is served from cache with zero AI API calls
```

## Key Technical Decisions Log

| # | Decision | We Chose | Over | Because |
|---|---|---|---|---|
| 1 | Full-stack architecture | FastAPI + Next.js (separate services) | Next.js API routes only | AI-adjacent work needs Python libraries (torch, transformers, pandas). Next.js API routes cannot run HuggingFace models. |
| 2 | Time-series storage | Native PostgreSQL partitioning + pg_partman | TimescaleDB | Timescale relicensed under the TSL, which conflicts with Supabase's open-source platform — new projects on Postgres 17+ can't enable it. Native partitioning delivers ~80% of the benefit at zero licensing risk. |
| 3 | Vector store | Supabase pgvector (same instance) | Pinecone / Weaviate / Qdrant | Cheaper, simpler, and removes a separate failure point and cost surface for a portfolio-scale project. |
| 4 | Forecasting model | Chronos-2 (self-hosted, CPU) | Hosted inference APIs | State-of-the-art zero-shot accuracy among public models, and CPU inference means it runs free on Render with no GPU cost. |
| 5 | Scheduler persistence | APScheduler + SQLAlchemyJobStore (Supabase) | APScheduler in-memory | APScheduler loses jobs on restart by default. Render's free tier restarts periodically — an in-memory scheduler would silently drop every job. |
| 6 | Map library | MapLibre GL JS + deck.gl | Leaflet / Google Maps | MapLibre is the open-source Mapbox fork — identical API, zero cost. Deck.gl renders 195 country polygons with live overlays at WebGL performance Leaflet can't match. |
| 7 | LLM architecture | Multi-provider rotation (Mistral → Groq → OpenRouter) | Single provider | Any single free-tier LLM will rate-limit under demo traffic. The rotation means the system never goes dark during a hiring manager's session. |
| 8 | LLM role boundary | LLM narrates numbers only — never generates them | LLM as end-to-end analyst | LLMs hallucinate statistics. Chronos-2 produces the numbers; the LLM only turns them into prose, and the groundedness verifier enforces this programmatically. |
| 9 | VLM pipeline | Server-side Plotly PNG → Gemini Flash | Client-side screenshot | Server-side rendering is deterministic and reproducible, unaffected by browser state or viewport size. |
| 10 | Embeddings | Sentence-Transformers fallback (self-hosted) | API-only embeddings | If Mistral's embedding API rate-limits, the system falls back to a locally-run model on Render's CPU — the RAG pipeline never goes fully offline. |

## Database Schema Outline

All tables reside in a single Supabase PostgreSQL instance.

```
data_sources
├── id (uuid, PK)
├── name (text) — "world_bank" | "imf" | "fred" | "bis" | "wb_databank"
├── base_url (text)
├── last_successful_run (timestamptz)
└── is_active (boolean)

indicators_catalog
├── id (uuid, PK)
├── source_id (uuid, FK → data_sources)
├── indicator_code (text) — e.g., "FP.CPI.TOTL.ZG"
├── indicator_name (text)
├── category (text) — "macroeconomic" | "financial" | "trade" | "social"
├── unit (text)
├── frequency (text) — "annual" | "quarterly" | "monthly"
└── description (text)

country_profiles
├── id (uuid, PK)
├── country_code (char(3), UNIQUE) — ISO 3166-1 alpha-3
├── country_name (text)
├── region (text) — e.g., "Sub-Saharan Africa" | "Caribbean" | "Central America"
├── income_classification (text) — World Bank income group
├── imf_classification (text) — "Advanced" | "Emerging" | "Developing"
├── population_bracket (text) — coarse bucket, not an exact figure
├── flag_emoji (text)
└── updated_at (timestamptz)

time_series  ← PARTITIONED BY RANGE (date) via pg_partman
├── id (uuid, PK)
├── country_code (char(3))
├── indicator_id (uuid, FK → indicators_catalog)
├── source_id (uuid, FK → data_sources)
├── date (date) — partition key
├── value (numeric)
├── is_validated (boolean)
└── ingested_at (timestamptz)
INDEXES: (country_code, indicator_id, date DESC)

anomalies
├── id (uuid, PK)
├── country_code (char(3))
├── indicator_id (uuid, FK → indicators_catalog)
├── date (date)
├── value (numeric)
├── z_score (numeric)
├── deviation_type (text) — "spike" | "drop" | "structural_break"
├── llm_explanation (text)
└── detected_at (timestamptz)

pipeline_runs
├── id (uuid, PK)
├── source_id (uuid, FK → data_sources)
├── started_at (timestamptz)
├── completed_at (timestamptz)
├── records_fetched (integer)
├── records_inserted (integer)
├── records_failed (integer)
└── status (text) — "success" | "partial" | "failed"

etl_errors
├── id (uuid, PK)
├── pipeline_run_id (uuid, FK → pipeline_runs)
├── raw_record (jsonb)
├── error_type (text)
├── error_message (text)
└── occurred_at (timestamptz)

llm_cache
├── id (uuid, PK)
├── cache_key (text, UNIQUE)
├── task_type (text) — "narration" | "anomaly_explanation" | "vlm_interpretation"
├── provider_used (text)
├── model_used (text)
├── response_text (text)
├── groundedness_score (numeric) — 0.0–1.0
├── token_count (integer)
├── cache_hit_count (integer)
├── created_at (timestamptz)
└── expires_at (timestamptz)

forecast_cache
├── id (uuid, PK)
├── cache_key (text, UNIQUE)
├── country_code (char(3))
├── indicator_id (uuid, FK → indicators_catalog)
├── model_used (text) — "chronos2" | "timesfm" | "statsforecast"
├── forecast_horizon (integer)
├── median_forecast (numeric[])
├── lower_bound (numeric[])
├── upper_bound (numeric[])
├── created_at (timestamptz)
└── expires_at (timestamptz)

embeddings  ← pgvector table
├── id (uuid, PK)
├── country_code (char(3))
├── indicator_id (uuid, FK → indicators_catalog)
├── chunk_text (text)
├── chunk_type (text) — "data_snapshot" | "country_profile" | "anomaly_context"
├── embedding (vector(384))
├── date_range_start (date)
├── date_range_end (date)
└── created_at (timestamptz)
INDEX: HNSW on embedding column (cosine distance)
```

## External Services, APIs & Models Required

- **Data sources:** World Bank (REST/JSON), IMF (SDMX 2.1/3.0), FRED (REST), BIS Statistics Portal, World Bank DataBank.
- **Infrastructure:** Supabase (Postgres + pgvector), Render (backend hosting), Vercel (frontend hosting), UptimeRobot (keep-alive), GitHub + GitHub Actions.
- **LLM providers:** Mistral, Groq, OpenRouter, Google AI Studio (Gemini Flash), Google Vertex AI (paid escape hatch — inactive by default).
- **Forecasting models:** Chronos-2 (amazon/chronos-2, HuggingFace), TimesFM (google/timesfm), Nixtla StatsForecast.
- **VLM:** Google AI Studio (Gemini Flash, native vision), Qwen3-VL (via OpenRouter).
- **Embeddings:** Mistral Embed, `sentence-transformers` (self-hosted fallback).

## Environment Variables

Names only — no values. Flagged Required or Optional.

```
# Supabase
SUPABASE_URL                    # Required
SUPABASE_ANON_KEY               # Required
SUPABASE_SERVICE_ROLE_KEY       # Required (backend only)
DATABASE_URL                    # Required (direct connection string for SQLAlchemy)

# Data Source API Keys
FRED_API_KEY                    # Required (free registration)
WORLD_BANK_API_KEY              # Optional (REST is keyless; key unlocks higher limits)
BIS_API_KEY                     # Optional (public API is keyless)

# LLM Providers
MISTRAL_API_KEY                 # Required
GROQ_API_KEY                    # Required
OPENROUTER_API_KEY              # Required
GOOGLE_AI_STUDIO_API_KEY        # Required

# Paid Escape Hatch (Optional — activate only if free tiers exhaust)
GOOGLE_VERTEX_AI_PROJECT_ID     # Optional
GOOGLE_VERTEX_AI_LOCATION       # Optional

# Application Config
NEXT_PUBLIC_API_URL             # Required
NEXT_PUBLIC_MAPTILER_KEY        # Optional (MapLibre runs keyless with OSM tiles)
ENVIRONMENT                     # Required — "development" | "staging" | "production"
LOG_LEVEL                       # Optional — default "INFO"

# Forecasting Config
CHRONOS2_MODEL_SIZE             # Optional — "mini" | "small" | "base" — default "mini"
FORECAST_CACHE_TTL_DAYS         # Optional — default 30
NARRATION_CACHE_TTL_HOURS       # Optional — default 24
VLM_CACHE_TTL_DAYS              # Optional — default 7

# Admin Access
ADMIN_HEALTH_TOKEN_HASH         # Required (hash only — never the raw token — gates /admin/health)
```
