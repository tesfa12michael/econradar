-- ─────────────────────────────────────────────────────────────
-- 0007_purge_aggregate_rows.sql — remove non-country rows (feature 1.1)
--
-- The World Bank and IMF both publish regional and income-group aggregates
-- alongside real countries, and many carry country-shaped codes: ARB (Arab
-- World), EMU (Euro area), WLD (World), plus the Global Economic Monitor's own
-- set (LAC, HIY, MIC, LIC...). An ISO-3 *shape* check cannot tell these apart
-- from a country, so early Phase 2 ingestions stored them as if they were.
--
-- Left in place they quietly corrupt every cross-country statistic: a "world
-- average" computed over a set that already contains "World" is wrong, and the
-- highest/lowest tiles surface groupings rather than countries.
--
-- The connectors now exclude these at normalize time by consulting each
-- provider's own country index (World Bank: region.id == "NA"; IMF: the
-- /countries endpoint), and abort the run outright if that index cannot be
-- loaded — a missed refresh is recoverable, silently-stored aggregates are not.
-- This migration only cleans up what already landed.
--
-- IMPORTANT: this deletes only codes on the explicit list below. An earlier
-- revision deleted anything absent from country_profiles, which would have
-- destroyed real data — the IMF reports Taiwan (TWN), West Bank and Gaza (WBG)
-- and Kosovo (UVK) under codes the World Bank registry does not use, so they are
-- absent from that seed while being perfectly valid economies. They are added by
-- seed 0008. Never re-broaden this to "not in country_profiles".
--
-- Idempotent: re-running deletes nothing once the data is clean.
-- ─────────────────────────────────────────────────────────────

create temporary table _aggregate_codes (code char(3) primary key);

insert into _aggregate_codes (code) values
    -- World Bank / WDI regional and lending groupings
    ('AFE'), ('AFW'), ('ARB'), ('CEB'), ('CSS'), ('EAP'), ('EAR'), ('EAS'),
    ('ECA'), ('ECS'), ('EMU'), ('EUU'), ('HPC'), ('IBD'), ('IBT'), ('IDA'),
    ('IDB'), ('IDX'), ('LAC'), ('LCN'), ('LDC'), ('LMY'), ('LTE'), ('MEA'),
    ('MIC'), ('MNA'), ('NAC'), ('OED'), ('OSS'), ('PRE'), ('PSS'), ('PST'),
    ('SAS'), ('SSA'), ('SSF'), ('SST'), ('TEA'), ('TEC'), ('TLA'), ('TMN'),
    ('TSA'), ('TSS'), ('WLD'), ('LIC'), ('LMC'), ('UMC'), ('HIC'), ('INX'),
    -- Global Economic Monitor (source 15) groupings
    ('HIY'), ('DEV'), ('EAA'), ('EDE'), ('EDI'), ('EDX'), ('EMD'), ('SSP'),
    ('LAP'), ('AME'), ('ECH'), ('SAP'), ('MNH'), ('WLT'),
    -- IMF WEO groupings that happen to be three characters
    ('AFR'), ('CEE'), ('EUR'), ('WEO')
on conflict (code) do nothing;

delete from anomalies a
where a.country_code in (select code from _aggregate_codes);

delete from time_series ts
where ts.country_code in (select code from _aggregate_codes);

drop table _aggregate_codes;
