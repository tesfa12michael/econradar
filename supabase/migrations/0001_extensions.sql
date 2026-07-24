-- ─────────────────────────────────────────────────────────────
-- 0001_extensions.sql — required Postgres extensions
-- Run first, on a fresh Supabase project.
-- ─────────────────────────────────────────────────────────────

-- pgvector: RAG embedding storage + HNSW similarity search (Phase 3).
create extension if not exists vector;

-- NOTE on pg_partman: enabling it is deferred to 0003a_partitioning_pg_partman.sql
-- because its availability must be VERIFIED per-project, not assumed
-- (see docs/strategy.md open questions). gen_random_uuid() is in Postgres core
-- (>= 13) on Supabase, so no pgcrypto extension is required for UUID defaults.
