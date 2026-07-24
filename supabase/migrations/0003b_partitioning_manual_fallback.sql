-- ─────────────────────────────────────────────────────────────
-- 0003b_partitioning_manual_fallback.sql — FALLBACK partitioning path
-- Use ONLY if pg_partman is unavailable on your Supabase project
-- (i.e. `create extension pg_partman` in 0003a fails).
--
-- RUN THIS *OR* 0003a_partitioning_pg_partman.sql — never both.
--
-- Creates one yearly partition 1960..2035 plus a catch-all DEFAULT partition,
-- so inserts for any date always land somewhere. New yearly partitions can be
-- added later with the same CREATE TABLE ... PARTITION OF pattern (or by
-- migrating to pg_partman once it becomes available).
-- ─────────────────────────────────────────────────────────────

do $$
declare
    y int;
begin
    for y in 1960..2035 loop
        execute format(
            'create table if not exists time_series_p%1$s '
            || 'partition of time_series for values from (%2$L) to (%3$L)',
            y, make_date(y, 1, 1), make_date(y + 1, 1, 1)
        );
    end loop;
end $$;

-- Catch-all so an out-of-range date never fails an insert.
create table if not exists time_series_default partition of time_series default;
