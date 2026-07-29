-- ─────────────────────────────────────────────────────────────
-- 0007_purge_aggregate_rows.sql — remove non-country rows (feature 1.1)
--
-- The World Bank and IMF both publish regional and income-group aggregates
-- alongside real countries, and several carry perfectly well-formed
-- three-letter codes: ARB (Arab World), EMU (Euro area), WLD (World),
-- SSF (Sub-Saharan Africa), and ~39 more. An ISO-3 *shape* check cannot tell
-- them apart from a country, so an early Phase 2 ingestion stored them as if
-- they were countries.
--
-- Left in place they would quietly corrupt every cross-country aggregate on
-- the dashboard — a "world average" computed over a set that already contains
-- "World" is wrong, and the highest/lowest tiles would surface groupings
-- rather than countries.
--
-- The connectors now exclude these at normalize time by consulting each
-- provider's own country index (World Bank: region.id == "NA"; IMF: the
-- /countries endpoint), so this only cleans up what already landed.
--
-- country_profiles is the authoritative list of the 217 real countries, and
-- is populated by seed 0005 independently of any ingestion.
--
-- Idempotent: re-running deletes nothing once the data is clean.
-- ─────────────────────────────────────────────────────────────

delete from anomalies a
where not exists (
    select 1 from country_profiles cp where cp.country_code = a.country_code
);

delete from time_series ts
where not exists (
    select 1 from country_profiles cp where cp.country_code = ts.country_code
);
