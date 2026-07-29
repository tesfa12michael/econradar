-- ─────────────────────────────────────────────────────────────
-- 0006_anomalies_unique.sql — natural key for anomaly upsert (feature 1.8)
--
-- Anomaly detection re-runs after every ingestion, and re-scoring an existing
-- point must update that row rather than append a duplicate. Without a natural
-- key the table would grow by the size of the flagged set on every pipeline run.
--
-- Unlike time_series, `anomalies` is NOT partitioned, so a plain UNIQUE
-- constraint is sufficient — the partition key does not have to participate.
--
-- Idempotent: safe to re-run. Any pre-existing duplicates are collapsed to the
-- most recently detected row before the constraint is added.
-- ─────────────────────────────────────────────────────────────

-- Collapse duplicates first, keeping the newest detection per natural key.
delete from anomalies a
using anomalies b
where a.country_code = b.country_code
  and a.indicator_id = b.indicator_id
  and a.date = b.date
  and (a.detected_at, a.id) < (b.detected_at, b.id);

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'anomalies_natural_key'
    ) then
        alter table anomalies
            add constraint anomalies_natural_key
            unique (country_code, indicator_id, date);
    end if;
end $$;

-- Supports "most recent anomalies across all countries" for the map's insight rail.
create index if not exists anomalies_detected_at_idx on anomalies (detected_at desc);
