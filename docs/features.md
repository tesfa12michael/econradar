<!-- filename: agent_docs/features.md -->
# Features

> Claude Code must update the status field of each feature at the end of every session.

Status legend: `[ ]` Not Started · `[~]` In Progress · `[x]` Complete

---

## Phase 1 — Foundation

### Foundation Infrastructure & First Connector
**Status:** [~] In Progress — backend code complete & locally verified (ruff clean; 18 unit tests + 1 live World Bank fetch green); frontend scaffolded (build/lint/test verification in progress). Live deploy (Vercel→Render→Supabase) and the scheduler-restart proof are pending cloud provisioning — see `DEPLOYMENT.md`.
**Description:** Repo scaffold, full Supabase schema migration (all tables from `architecture.md`), deployed FastAPI/Next.js skeleton, `BaseDataSourceConnector` abstract class with a working World Bank connector as proof of concept, APScheduler wired to a persisted `SQLAlchemyJobStore`, GitHub Actions CI, UptimeRobot keep-alive.
**Acceptance Criteria:** A public Vercel frontend calls a public Render backend, which reads real World Bank data out of Supabase through one working API endpoint; the scheduled job survives a manual backend restart; CI is green on `main`.
**Known Edge Cases:** `pg_partman` extension availability must be verified at Supabase project creation, not assumed; Render/Vercel first-deploy configuration quirks (env var propagation, build command detection).
**Dependencies:** None — this is the starting point for everything else.

### 1.3 Time-Series Storage (Supabase PostgreSQL)
**Status:** [~] In Progress — full schema migration (all 10 tables), `time_series` RANGE partitioning (pg_partman primary + manual fallback), and reference/country seeds are written; not yet applied to a live Supabase project. See `supabase/README.md` and `DEPLOYMENT.md`.
**Description:** Partitioned time-series tables via `pg_partman`, organized by `(country_code, indicator_code, source, date)`, plus the `indicators_catalog`, `data_sources`, and `country_profiles` metadata tables.
**Acceptance Criteria:** Schema migration runs cleanly on a fresh Supabase project; partitions are created/pruned automatically as data spans years; a single country/indicator lookup stays fast as volume grows.
**Known Edge Cases:** A country/indicator with decades of monthly data vs. one with a single annual data point — the partition strategy must handle both without special-casing.
**Dependencies:** None.

---

## Phase 2 — Core Feature(s)

### 1.1 Multi-Source Data Ingestion Pipeline
**Status:** [ ] Not Started
**Description:** Connector classes for IMF, FRED, BIS, and World Bank DataBank, completing the plugin set started with World Bank in Phase 1. Each handles its own pagination, rate limits, and schema normalization into a shared `TimeSeriesRecord` model.
**Acceptance Criteria:** All five connectors successfully fetch and normalize data for a full test set of countries/indicators; each is independently retriable without affecting the others.
**Known Edge Cases:** IMF SDMX responses with nested/multi-dimensional structures that don't map 1:1 to a flat record; FRED series with gaps or discontinuations; country codes that don't align across sources (e.g., disputed territories); 429 rate-limit responses needing backoff, not failure.
**Dependencies:** Foundation Infrastructure (Phase 1).

### 1.2 ETL Validation, Cleaning & Failure Logging
**Status:** [ ] Not Started
**Description:** Per-record validation (null checks, type enforcement, outlier flags, timestamp continuity) across all five sources; malformed records logged to `etl_errors`, never dropped silently.
**Acceptance Criteria:** Every rejected record has a corresponding `etl_errors` row with `raw_record`, `error_type`, and `error_message`; a pipeline run's status accurately reflects its error count.
**Known Edge Cases:** A record that's syntactically valid but semantically implausible (that's anomaly detection's job, not ETL's — the boundary must stay documented); duplicate records from overlapping re-runs; a source changing its schema without notice.
**Dependencies:** 1.1.

### 1.6 Interactive World Map
**Status:** [ ] Not Started
**Description:** MapLibre GL JS + deck.gl choropleth, color-coded by the selected indicator, clickable through to country profiles, anomaly-flagged countries marked visually.
**Acceptance Criteria:** Renders all covered countries with correct color-scale shading; hover and click work via mouse and keyboard; anomaly markers are visually distinct.
**Known Edge Cases:** A country with no data for the selected indicator must render distinctly, not as a false zero; disputed-territory borders may not match every source's country list; very small countries are hard to click at world scale.
**Dependencies:** 1.1, 1.3.

### 1.7 Country Profile Page (Shell)
**Status:** [ ] Not Started
**Description:** Historical time-series chart (Recharts), indicator selector tabs, key metrics cards. Forecast overlay, LLM narration panel, and VLM panel are visible as clearly-labeled "coming soon" placeholders — full integration completes in Phase 3.
**Acceptance Criteria:** Every country's page shows a real historical chart with anomaly badges; layout is legible and functional on both desktop and mobile.
**Known Edge Cases:** A country/indicator combination with sparse or no data needs a real empty state, not a broken layout.
**Dependencies:** 1.3, 1.6.

### 1.8 Statistical Anomaly Detection
**Status:** [ ] Not Started
**Description:** Rolling Z-score / IQR flagging, default ±2σ threshold, stored in `anomalies`, surfaced as badges on the map and profile page (magnitude and timestamp only — no LLM explanation yet).
**Acceptance Criteria:** Anomalies are detected and stored automatically as new data is ingested; badges appear consistently on both surfaces; threshold is configurable, not hardcoded.
**Known Edge Cases:** A naturally volatile indicator (e.g., a small economy's GDP growth) may falsely flag constantly under a fixed threshold; the first few points of a new series lack enough history for a meaningful rolling Z-score.
**Dependencies:** 1.3.

### 2.4 Scheduled Data Refresh (Full Cadence)
**Status:** [ ] Not Started
**Description:** Per-source refresh cadence in APScheduler — World Bank/IMF weekly, FRED daily, BIS/WB DataBank monthly — extending the single Phase 1 job to all five sources.
**Acceptance Criteria:** Each source refreshes on its configured schedule without manual intervention; job history survives a backend restart.
**Known Edge Cases:** Overlapping runs if a job takes longer than its interval; a source unreachable for an extended period shouldn't crash the scheduler.
**Dependencies:** 1.1, Foundation Infrastructure.

---

## Phase 3 — Intelligence Layer

### 1.4 Zero-Shot Forecasting Engine
**Status:** [ ] Not Started
**Description:** Chronos-2 (mini, CPU) → TimesFM → Nixtla StatsForecast cascade producing 12-month quantile forecasts, cached in `forecast_cache`.
**Acceptance Criteria:** A forecast request for any indicator with sufficient history returns median/p10/p90 arrays; the cascade falls back correctly when a higher-priority model errors or times out.
**Known Edge Cases:** A series too short for meaningful forecasting; structural breaks (redenomination, war, COVID-era discontinuities) that could produce a nonsensical forecast; Chronos-2 timing out on free-tier CPU.
**Dependencies:** 1.3.

### 1.5 LLM Narration Layer
**Status:** [ ] Not Started
**Description:** Multi-provider rotation (Mistral → Groq → OpenRouter) behind one `LLMService` interface; Jinja2-templated prompts narrate precomputed numbers; groundedness verifier checks every number against source context.
**Acceptance Criteria:** Narration generates for any country/indicator with data; every numeric claim is verifiable against the input context; provider fallback triggers correctly on rate-limit and is logged.
**Known Edge Cases:** The LLM paraphrasing a number in a way the verifier can't parse ("roughly a fifth" vs. "20%"); all three providers rate-limiting simultaneously; negative or zero values producing awkward phrasing.
**Dependencies:** 1.3, 1.4.

### 2.1 VLM Chart Interpretation Layer ⭐ Signature Feature
**Status:** [ ] Not Started
**Description:** Server-side Plotly chart-to-PNG rendering → Gemini Flash (primary) → Qwen3-VL via OpenRouter (fallback); structured interpretive narrative on trend direction, inflection points, and volatility.
**Acceptance Criteria:** A chart-to-narrative interpretation is generated and displayed for any country profile chart; cached with a 7-day TTL; fallback triggers correctly on Gemini rate-limit.
**Known Edge Cases:** A visually ambiguous chart (flat line, single data point) gives the VLM nothing meaningful to interpret; the VLM describing something not actually in the chart needs the same groundedness discipline as text narration; silent image-rendering failures must error loudly.
**Dependencies:** 1.3, 1.4.

### 2.2 RAG-Powered Economic Q&A ⭐ Signature Feature
**Status:** [ ] Not Started
**Description:** Hybrid retrieval (pgvector semantic search + metadata filtering) chat interface; grounded, cited answers; streamed via Groq; multi-turn context (last 4 turns).
**Acceptance Criteria:** A cross-country question returns a grounded answer with clickable citation cards; an "insufficient data" fallback triggers instead of a fabricated answer when retrieval returns nothing relevant.
**Known Edge Cases:** A question referencing a country/indicator combination with no embedded data; an ambiguous question spanning many countries that retrieval must not silently truncate; off-domain questions must decline gracefully, not hallucinate.
**Dependencies:** 1.3, populated `embeddings` table.

### 2.3 LLM-Grounded Anomaly Explanations
**Status:** [ ] Not Started
**Description:** Anomaly + 12-month context + Z-score fed to `LLMService`; grounded explanation stored on `anomalies.llm_explanation`.
**Acceptance Criteria:** Every stored anomaly has a corresponding grounded explanation; the explanation cites only numbers present in the provided context.
**Known Edge Cases:** An anomaly with an ambiguous real-world cause — the LLM must not invent a plausible-sounding but unverifiable driver; multiple close-together anomalies must be distinguished, not conflated.
**Dependencies:** 1.8, 1.5.

### 1.7 Country Profile Page (Completion)
**Status:** [ ] Not Started
**Description:** Replaces all Phase 2 "coming soon" placeholders with live forecast overlay, narration panel, and VLM panel, working together on one page.
**Acceptance Criteria:** All three signature features are simultaneously and visibly functioning on a real profile page; slow AI panel responses never block the historical chart from rendering; switching indicators mid-load cancels the stale request rather than racing it.
**Known Edge Cases:** Same data-sparsity edge cases as the Phase 2 shell, now compounded across three additional async panels.
**Dependencies:** 1.4, 1.5, 2.1, 2.3.

### 2.5 LLM Response Caching Layer
**Status:** [ ] Not Started
**Description:** Composite-key caching (country + indicator + window + model + task type) built into `ForecastingService`, `LLMService`, and `VLMService` from the start — not bolted on afterward.
**Acceptance Criteria:** A repeated request for the same country/indicator/time-window is served from cache with zero external API calls; cache respects its TTL and regenerates after expiry; hit rate is measurable for Phase 4's observability dashboard.
**Known Edge Cases:** A cache key collision between similar but distinct requests; stale cache serving outdated data after a source correction — TTL must be short enough that this is rare, with a manual invalidation path available.
**Dependencies:** 1.4, 1.5, 2.1.

---

## Phase 4 — Polish & Production Readiness

### 2.6 Observability & Pipeline Health Dashboard
**Status:** [ ] Not Started
**Description:** Public curated `/status` page (sanitized signals only) plus a private, token-gated `/admin/health` dashboard (full pipeline/LLM/forecast internals).
**Acceptance Criteria:** `/status` is reachable by anyone and shows only the approved sanitized fields; `/admin/health` rejects any request without a valid token hash; both reflect real, current system state.
**Known Edge Cases:** A token brute-force attempt against `/admin/health` should rate-limit or lock out, not just reject silently forever; `/status` must not leak a granular detail through an overly-specific aggregate (e.g., a count of exactly 1 revealing which single source failed).
**Dependencies:** 2.4, 2.5, and every pipeline/AI service generating the data being observed.

### 2.7 Multi-Indicator Comparison View
**Status:** [ ] Not Started
**Description:** Side-by-side chart view — 2–4 indicators across 1–3 countries on a shared time axis, with comparative LLM narration.
**Acceptance Criteria:** Any valid combination within the stated limits renders a correctly-scaled shared-axis chart; comparative narration references all selected countries/indicators, not just the first one.
**Known Edge Cases:** Indicators with wildly different units/scales (GDP in trillions vs. inflation in percent) needing dual axes or normalization; selected series with no overlapping date range.
**Dependencies:** 1.3, 1.6/1.7 infrastructure.

### Case Study PDF (Portfolio Deliverable)
**Status:** [ ] Not Started
**Description:** Deep, standalone case-study document for the portfolio website — distinct from the README and `DEMO_SCRIPT.md`. Built entirely in this phase from real metrics, screenshots, and build challenges. Source material: `strategy.md`, `architecture.md`, this file, `PROGRESS.md`'s full decision history, and the original research conversation.
**Acceptance Criteria:** Reads as a finished professional document, not speculative placeholders; cites real figures and real screenshots from the running system; exported to a polished PDF ready for upload.
**Known Edge Cases:** The build not producing a genuinely interesting challenge to write about for some section — stay honest rather than padding; scope creep into a second README instead of a real deep-dive.
**Dependencies:** All of Phases 1–4, `PROGRESS.md`, `agent_docs/`, original research document.

*(Also in this phase: the WCAG 2.1 AA accessibility pass, free-tier production hardening, the `/admin/health` security pass, and the README documentation pass — these are process/QA tasks rather than standalone features, tracked directly in `PROGRESS.md` rather than as scored entries here.)*

---

## Phase 5+ — Stretch Goals (Optional)

### 3.1 Multi-Model Forecasting Ensemble
**Status:** [ ] Not Started
**Description:** Backtested, weighted blend of Chronos-2, TimesFM, and StatsForecast outputs, weighted per indicator category.
**Acceptance Criteria:** Ensemble forecast outperforms or is demonstrably comparable to the single best cascade model on a backtest set; per-model confidence bands remain individually inspectable.
**Known Edge Cases:** One model failing for a given series — the ensemble must degrade to the remaining models, not fail entirely; backtest data too sparse for a category to compute reliable weights.
**Dependencies:** 1.4.

### 3.2 OECD & Eurostat Connector Activation
**Status:** [ ] Not Started
**Description:** Activates the pre-built plugin slots for OECD (SDMX-JSON) and Eurostat (SDMX 2.1).
**Acceptance Criteria:** Both connectors ingest real data through the existing `BaseDataSourceConnector` pattern with no changes to core ETL/storage code.
**Known Edge Cases:** Overlapping country/indicator coverage with existing sources needs a defined precedence rule, not silent duplication or conflict.
**Dependencies:** 1.1's plugin architecture.

### 3.3 AI-Generated Country Economic Report (PDF)
**Status:** [ ] Not Started
**Description:** One-click LLM-orchestrated PDF briefing (WeasyPrint/ReportLab), structured like an IMF Article IV consultation.
**Acceptance Criteria:** Generates for any country with sufficient data, cites every figure, renders correctly as a downloadable PDF.
**Known Edge Cases:** A country with too little data to fill every section must gracefully omit, not fabricate; long generation time for data-rich countries needs an async job pattern, not a blocking request.
**Dependencies:** 1.4, 1.5, 1.8, 2.1, 2.3.

### 3.4 Public REST API Endpoint
**Status:** [ ] Not Started
**Description:** Versioned, documented, rate-limited (Supabase RLS + API keys) public API at `/api/v1/`.
**Acceptance Criteria:** A third-party developer can obtain a key, query documented endpoints, and receive correctly rate-limited responses with clear error messages on limit exceeded.
**Known Edge Cases:** Abuse far beyond a key's rate limit needs throttling that doesn't degrade the main dashboard's own performance; versioning a breaking change without disrupting existing consumers.
**Dependencies:** The full FastAPI API layer.

### 3.5 User Alert Subscriptions
**Status:** [ ] Not Started
**Description:** Email/webhook subscriptions on country/indicator pairs via Supabase Edge Functions + Resend, triggered by anomaly detection.
**Acceptance Criteria:** A subscribed user receives a notification within a reasonable delay of an anomaly being detected; unsubscribing correctly stops future notifications.
**Known Edge Cases:** A burst of simultaneous anomalies across many countries needs batching/digest logic instead of a flood; invalid or bouncing email/webhook targets must not retry forever.
**Dependencies:** 1.8.

### 3.6 Aurora TSFM Integration
**Status:** [ ] Not Started
**Description:** Experimental fourth forecasting model from ICLR 2026, added to the cascade once the model and its tooling stabilize.
**Acceptance Criteria:** Integrated only behind an explicit "experimental" flag/label; never replaces the existing cascade's default behavior.
**Known Edge Cases:** Upstream model/tooling instability or breaking changes must not be allowed to break the existing Chronos-2/TimesFM/StatsForecast cascade.
**Dependencies:** 1.4.
