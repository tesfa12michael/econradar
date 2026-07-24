-- ─────────────────────────────────────────────────────────────
-- 0003a_partitioning_pg_partman.sql — PRIMARY partitioning path
-- Targets pg_partman v5 (the version Supabase currently ships).
--
-- RUN THIS *OR* 0003b_partitioning_manual_fallback.sql — never both.
-- If `create extension pg_partman` fails on your project, use 0003b.
-- (docs/strategy.md flags pg_partman availability as verify-at-build-time.)
-- ─────────────────────────────────────────────────────────────

create extension if not exists pg_partman schema partman;

-- Turn time_series into a pg_partman-managed, yearly range-partitioned table.
-- World Bank annual series reach back to 1960, so start partitions there and let
-- premake keep a few years ahead of "now". p_default_table := true creates a
-- catch-all partition so an insert never fails for a missing partition.
select partman.create_parent(
    p_parent_table    := 'public.time_series',
    p_control         := 'date',
    p_interval        := '1 year',
    p_type            := 'range',
    p_premake         := 4,
    p_start_partition := '1960-01-01',
    p_default_table   := true
);

-- Keep everything (economic history is never pruned): disable retention.
update partman.part_config
set    retention = null,
       automatic_maintenance = 'on'
where  parent_table = 'public.time_series';

-- Optional: schedule daily maintenance so future partitions are created
-- automatically. Requires pg_cron (available on Supabase). Uncomment to enable:
-- select cron.schedule('partman-maintenance', '0 3 * * *',
--                      $$call partman.run_maintenance_proc()$$);
