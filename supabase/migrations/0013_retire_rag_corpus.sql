-- ─────────────────────────────────────────────────────────────
-- 0013_retire_rag_corpus.sql — delete what the agent replaced
--
-- **This migration deletes data. It was approved by the owner explicitly**, on
-- 2026-08-01, after both systems it removes had been dead for a full session.
-- Nothing here is reversible from inside the database, and both objects are
-- derived rather than source data: the corpus is rebuilt from `time_series`, and
-- the cache rows are model output that can be regenerated.
--
-- **The corpus.** `embeddings` held 9,263 chunks with a 384-d vector each, built
-- for the retrieval path that decision #38 removed. Since the chatbot became an
-- agent over two SQL tools, nothing reads the table: no query, no route, no job
-- consumes it, and a weekly job was still rebuilding it. A corpus with no reader
-- is not a fallback, it is 49 MB of a 500 MB tier plus one scheduled rebuild
-- spending CPU on a 1 vCPU box every Monday.
--
-- **The narration rows.** Decision #35 removed the AI narration panel whole. Its
-- `llm_cache` rows were deliberately left behind at the time, because deleting
-- data is the owner's call and nothing was reading them either way — no code path
-- can produce another, since `TASK_NARRATION` no longer exists.
--
-- Idempotent and safe to re-run: `drop table if exists` and a delete with a
-- predicate that matches nothing the second time.
--
-- Deliberately NOT dropped: the `vector` extension (0001_extensions.sql). It is
-- inert without a vector column, dropping it reclaims nothing measurable, and
-- leaving it means a future feature that wants embeddings is one `create table`
-- rather than an extension request against a managed database.
-- ─────────────────────────────────────────────────────────────

-- ── the RAG corpus ───────────────────────────────────────────
-- Takes the HNSW index (0002) and the chunk_key/filter indexes (0010) with it,
-- which is where most of the 49 MB actually sits.
drop table if exists embeddings;

-- ── narration cache rows ─────────────────────────────────────
-- Scoped by task_type, not by prefix: the other three task types are live and
-- must not be touched. `anomaly_explanation`, `vlm_interpretation` and
-- `rag_answer` all still have readers.
delete from llm_cache where task_type = 'narration';
