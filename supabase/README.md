# Supabase schema & seeds

Apply these against a **fresh** Supabase project (Postgres 15) — SQL Editor or `psql`.
Run them **in order**. Files are idempotent where practical, but the partitioning step is
a one-time choice (see below).

| Order | File | Purpose |
|---|---|---|
| 1 | `migrations/0001_extensions.sql` | Enable `pgvector`. |
| 2 | `migrations/0002_schema.sql` | All 10 tables, indexes, constraints. `time_series` is created as a RANGE-partitioned parent. |
| 3 | `migrations/0003a_partitioning_pg_partman.sql` | **Primary** partitioning path (pg_partman v5). |
| 3 (alt) | `migrations/0003b_partitioning_manual_fallback.sql` | **Fallback** — use only if step 3a's `create extension pg_partman` fails. |
| 4 | `seeds/0004_seed_reference.sql` | `data_sources` + `indicators_catalog`. |
| 5 | `seeds/0005_seed_country_profiles.sql` | 217 `country_profiles` (generated from the World Bank registry). |

## The partitioning decision (read before step 3)

`docs/strategy.md` flags pg_partman availability as **verify-at-build-time, not assumed**.
So:

1. Try `0003a_partitioning_pg_partman.sql` first.
2. If the very first line — `create extension if not exists pg_partman` — errors because the
   extension isn't available on your project, run `0003b_partitioning_manual_fallback.sql` instead.
3. **Run exactly one of them.** They are mutually exclusive: 0003a hands partition management to
   pg_partman; 0003b creates fixed yearly partitions (1960–2035) plus a `DEFAULT` catch-all.

Record which path you took in `PROGRESS.md`.

## Verify

```sql
-- 10 base tables present?
select count(*) from information_schema.tables
where table_schema = 'public'
  and table_name in ('data_sources','indicators_catalog','country_profiles','time_series',
                     'anomalies','pipeline_runs','etl_errors','llm_cache','forecast_cache','embeddings');
-- expect 10

-- time_series is partitioned + has children?
select count(*) from pg_inherits
where inhparent = 'public.time_series'::regclass;   -- expect > 0

-- reference data seeded?
select (select count(*) from data_sources)        as sources,       -- 5
       (select count(*) from indicators_catalog)   as indicators,    -- 8
       (select count(*) from country_profiles)     as countries;     -- 217
```

## Regenerating the country seed

```bash
python backend/scripts/generate_country_seed.py
```

Rewrites `seeds/0005_seed_country_profiles.sql` from the live World Bank registry.
`imf_classification` is a documented heuristic (see the script's docstring), not fetched IMF data.
