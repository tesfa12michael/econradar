-- ─────────────────────────────────────────────────────────────
-- 0009_purge_fred_daily_yield.sql — drop the daily US 10-year yield (feature 1.1)
--
-- FRED.GOV10Y is a cross-country indicator: the same measurement under one code so
-- Germany, the UK, Japan and the US line up on a chart and in a ranking. The US leg
-- was DGS10, the *daily* constant-maturity yield, while the other three were the
-- OECD-harmonised *monthly* series. That is not the same measurement:
--
--   * 16,127 US observations against ~800 for each peer — the US swamps any
--     cross-country aggregate over this indicator purely by row count, and produced
--     2,210 of FRED's 3,121 anomalies on its own;
--   * indicators_catalog carries one frequency per indicator, so a single column had
--     to describe both daily and monthly data, and whichever ingested last won;
--   * a profile chart plotting 16k daily points beside 800 monthly ones compares
--     noise against a smoothed series.
--
-- The connector now uses IRLTLT01USM156N — the like-for-like monthly OECD series for
-- the US, which also starts earlier (1953-04 vs 1962-01) and so covers every month
-- DGS10 did. Re-ingestion repopulates this indicator immediately after this runs.
--
-- SAFE TO RE-RUN. Unlike an aggregate purge, this deletes an (indicator, country)
-- pair the connector legitimately refills, so a naive version would destroy the
-- corrected data on a second application — the same class of landmine 0007 warns
-- about. The guard below fires only while daily-dated rows are actually present; once
-- the series is monthly it is false and every statement here is a no-op.
-- ─────────────────────────────────────────────────────────────

create temporary table _fred_daily_contamination as
select exists (
    select 1
      from time_series ts
      join indicators_catalog i on i.id = ts.indicator_id
      join data_sources s on s.id = i.source_id
     where s.name = 'fred'
       and i.indicator_code = 'FRED.GOV10Y'
       and ts.country_code = 'USA'
       -- Monthly observations are stored on the first of the period; anything else
       -- can only have come from the daily series.
       and extract(day from ts.date) <> 1
) as contaminated;

delete from anomalies a
 using indicators_catalog i, data_sources s
 where a.indicator_id = i.id
   and i.source_id = s.id
   and s.name = 'fred'
   and i.indicator_code = 'FRED.GOV10Y'
   and a.country_code = 'USA'
   and (select contaminated from _fred_daily_contamination);

delete from time_series ts
 using indicators_catalog i, data_sources s
 where ts.indicator_id = i.id
   and i.source_id = s.id
   and s.name = 'fred'
   and i.indicator_code = 'FRED.GOV10Y'
   and ts.country_code = 'USA'
   and (select contaminated from _fred_daily_contamination);

drop table _fred_daily_contamination;
