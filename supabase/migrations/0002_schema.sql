-- ─────────────────────────────────────────────────────────────
-- 0002_schema.sql — EconRadar core schema (all Phase 1 tables)
-- Mirrors docs/architecture.md § "Database Schema Outline".
-- Several tables (llm_cache, forecast_cache, embeddings) stay empty
-- until Phase 3 but are created now so no later phase alters the schema
-- outside a logged migration.
-- Run AFTER 0001_extensions.sql, BEFORE a partitioning file (0003a/0003b).
-- ─────────────────────────────────────────────────────────────

-- ── data_sources ─────────────────────────────────────────────
create table if not exists data_sources (
    id                   uuid primary key default gen_random_uuid(),
    name                 text not null unique,       -- world_bank | imf | fred | bis | wb_databank
    base_url             text not null,
    last_successful_run  timestamptz,
    is_active            boolean not null default true
);

-- ── country_profiles ─────────────────────────────────────────
-- Static reference data. Kept separate so a country name/region lookup
-- never joins the large time_series table (see PROGRESS.md decision log).
create table if not exists country_profiles (
    id                     uuid primary key default gen_random_uuid(),
    country_code           char(3) not null unique,  -- ISO 3166-1 alpha-3
    country_name           text not null,
    region                 text,
    income_classification  text,                     -- World Bank income group
    imf_classification     text,                     -- Advanced | Emerging | Developing
    population_bracket     text,                     -- coarse bucket, not an exact figure
    flag_emoji             text,
    updated_at             timestamptz not null default now()
);

-- ── indicators_catalog ───────────────────────────────────────
create table if not exists indicators_catalog (
    id              uuid primary key default gen_random_uuid(),
    source_id       uuid not null references data_sources(id) on delete cascade,
    indicator_code  text not null,                   -- e.g. FP.CPI.TOTL.ZG
    indicator_name  text not null,
    category        text,                            -- macroeconomic | financial | trade | social
    unit            text,
    frequency       text,                            -- annual | quarterly | monthly
    description     text,
    unique (source_id, indicator_code)
);

-- ── time_series ──────────────────────────────────────────────
-- PARTITIONED BY RANGE (date). A partitioned table requires every
-- unique/primary-key constraint to include the partition key (date),
-- hence the composite PK (id, date) and the (country_code, indicator_id, date)
-- uniqueness. Child partitions are created in 0003a (pg_partman) or 0003b (manual).
create table if not exists time_series (
    id            uuid not null default gen_random_uuid(),
    country_code  char(3) not null,
    indicator_id  uuid not null references indicators_catalog(id) on delete cascade,
    source_id     uuid not null references data_sources(id) on delete cascade,
    date          date not null,
    value         numeric,
    is_validated  boolean not null default false,
    ingested_at   timestamptz not null default now(),
    constraint time_series_pkey primary key (id, date),
    -- Serves upsert (ON CONFLICT) AND the documented (country_code, indicator_id,
    -- date DESC) lookup: a btree unique index scans backwards for DESC ordering,
    -- so a separate DESC index would be redundant. (Deviation logged in PROGRESS.md.)
    constraint time_series_natural_key unique (country_code, indicator_id, date)
) partition by range (date);

-- ── anomalies ────────────────────────────────────────────────
create table if not exists anomalies (
    id              uuid primary key default gen_random_uuid(),
    country_code    char(3) not null,
    indicator_id    uuid not null references indicators_catalog(id) on delete cascade,
    date            date not null,
    value           numeric,
    z_score         numeric,
    deviation_type  text,                            -- spike | drop | structural_break
    llm_explanation text,
    detected_at     timestamptz not null default now()
);
create index if not exists anomalies_country_indicator_idx
    on anomalies (country_code, indicator_id, date desc);

-- ── pipeline_runs ────────────────────────────────────────────
create table if not exists pipeline_runs (
    id                uuid primary key default gen_random_uuid(),
    source_id         uuid not null references data_sources(id) on delete cascade,
    started_at        timestamptz not null default now(),
    completed_at      timestamptz,
    records_fetched   integer not null default 0,
    records_inserted  integer not null default 0,
    records_failed    integer not null default 0,
    status            text not null default 'running' -- running | success | partial | failed
);
create index if not exists pipeline_runs_source_started_idx
    on pipeline_runs (source_id, started_at desc);

-- ── etl_errors ───────────────────────────────────────────────
-- Malformed records are logged here, never silently dropped (feature 1.2).
create table if not exists etl_errors (
    id               uuid primary key default gen_random_uuid(),
    pipeline_run_id  uuid not null references pipeline_runs(id) on delete cascade,
    raw_record       jsonb,
    error_type       text,
    error_message    text,
    occurred_at      timestamptz not null default now()
);
create index if not exists etl_errors_run_idx on etl_errors (pipeline_run_id);

-- ── llm_cache ────────────────────────────────────────────────
create table if not exists llm_cache (
    id                 uuid primary key default gen_random_uuid(),
    cache_key          text not null unique,
    task_type          text,                         -- narration | anomaly_explanation | vlm_interpretation
    provider_used      text,
    model_used         text,
    response_text      text,
    groundedness_score numeric,                      -- 0.0–1.0
    token_count        integer,
    cache_hit_count    integer not null default 0,
    created_at         timestamptz not null default now(),
    expires_at         timestamptz
);
create index if not exists llm_cache_expires_idx on llm_cache (expires_at);

-- ── forecast_cache ───────────────────────────────────────────
create table if not exists forecast_cache (
    id                uuid primary key default gen_random_uuid(),
    cache_key         text not null unique,
    country_code      char(3) not null,
    indicator_id      uuid not null references indicators_catalog(id) on delete cascade,
    model_used        text,                          -- chronos2 | timesfm | statsforecast
    forecast_horizon  integer,
    median_forecast   numeric[],
    lower_bound       numeric[],
    upper_bound       numeric[],
    created_at        timestamptz not null default now(),
    expires_at        timestamptz
);
create index if not exists forecast_cache_expires_idx on forecast_cache (expires_at);

-- ── embeddings (pgvector) ────────────────────────────────────
create table if not exists embeddings (
    id                uuid primary key default gen_random_uuid(),
    country_code      char(3),
    indicator_id      uuid references indicators_catalog(id) on delete cascade,
    chunk_text        text not null,
    chunk_type        text,                          -- data_snapshot | country_profile | anomaly_context
    embedding         vector(384),
    date_range_start  date,
    date_range_end    date,
    created_at        timestamptz not null default now()
);
-- HNSW index for cosine-distance semantic search (pgvector >= 0.5).
create index if not exists embeddings_hnsw_idx
    on embeddings using hnsw (embedding vector_cosine_ops);
