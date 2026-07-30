-- ─────────────────────────────────────────────────────────────
-- 0010_embeddings_chunk_key.sql — make the RAG corpus rebuildable in place
-- Feature 2.2. Logged in PROGRESS.md per the CLAUDE.md hard rule.
--
-- The corpus is regenerated on a weekly cadence as new observations land. Without
-- a natural key that means either duplicating every chunk on each run, or deleting
-- the whole corpus first — which leaves the chat endpoint with nothing to retrieve
-- for the several minutes the rebuild takes. A stable per-chunk key lets the
-- refresh upsert, so the corpus is always complete and always current.
--
-- Deliberately a single generated text key rather than a composite UNIQUE over
-- (chunk_type, country_code, indicator_id, date_range_start): two of those columns
-- are nullable, and in Postgres NULLs are distinct in a unique index, so the
-- constraint would silently not apply to exactly the country-level chunks that
-- have no indicator. PG15+ has NULLS NOT DISTINCT, but a key the application
-- computes is also the key it can look up and invalidate by, which the composite
-- is not.
--
-- Idempotent: safe to re-run.
-- ─────────────────────────────────────────────────────────────

alter table embeddings add column if not exists chunk_key text;

-- Any rows predating this column cannot be matched to a source chunk, so they
-- would never be updated and never retrievable in a predictable way. The corpus
-- is derived data and is rebuilt from time_series on the next refresh.
delete from embeddings where chunk_key is null;

alter table embeddings alter column chunk_key set not null;

create unique index if not exists embeddings_chunk_key_uidx
    on embeddings (chunk_key);

-- Backs the metadata half of the hybrid retrieval in feature 2.2: the vector
-- search is narrowed by country and chunk type before distances are compared.
create index if not exists embeddings_filter_idx
    on embeddings (country_code, chunk_type);
