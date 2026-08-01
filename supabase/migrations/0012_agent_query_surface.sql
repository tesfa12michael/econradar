-- ─────────────────────────────────────────────────────────────
-- 0012_agent_query_surface.sql — one row that answers the whole question
--
-- Answering "what is Japan's unemployment rate" correctly needs the value, the
-- date it was observed, who published it, what kind of number it is, and what it
-- is not comparable with. Those lived in four tables, so anything reading the
-- database had to remember to join all four — and the thing about to read it is a
-- language model, which will not.
--
-- Views rather than materialized views, deliberately. A materialized latest-value
-- table would be ~3,000 rows and very fast, but it would also be *wrong between
-- refreshes*, and a stale ranking is the exact failure this work exists to remove.
-- The measurement below says it is not needed: with the index added at the bottom
-- of this file, ranking every country on one indicator runs in ~70 ms against
-- ~2,100 ms without it. Correct by construction beats fast and refreshable.
-- ─────────────────────────────────────────────────────────────

-- ── every observation, fully described ───────────────────────
-- NULL values are excluded on purpose: a NULL is the *absence* of an observation,
-- and every consumer of this view is trying to state what a number is. Nothing can
-- accidentally report one as a reading.
create or replace view v_observations as
select
    ts.country_code,
    cp.country_name,
    cp.region,
    cp.income_classification,
    ic.indicator_code,
    ic.indicator_name,
    ic.category,
    ic.unit,
    ic.frequency,
    ic.concept,
    ic.metric_type,
    ic.transformation,
    ic.observation_basis,
    ic.price_basis,
    ic.coverage_definition,
    ic.seasonal_adjustment,
    ic.is_primary_for_concept,
    ic.comparability_notes,
    ds.name as source,
    ts.date  as observation_date,
    ts.value,
    ts.is_validated,
    ts.ingested_at
from time_series ts
join indicators_catalog ic on ic.id = ts.indicator_id
-- ts.source_id, not ic.source_id: this says who supplied *this observation*.
join data_sources ds on ds.id = ts.source_id
left join country_profiles cp on cp.country_code = ts.country_code
where ts.value is not null;

comment on view v_observations is
    'Observations with their full indicator, source and country context — the single
     surface the agent queries. One row carries everything needed to state a figure
     without ambiguity: the value, when it was observed, who published it, whether it
     is year-over-year or a level, an average or a year-end stock, and what it must
     not be compared with. NULL values are excluded.';

-- ── the current reading for each country and indicator ───────
-- Not built on v_observations, and the difference is measurable. Layering DISTINCT
-- ON over that view resolves the country and source joins for every one of an
-- indicator's ~6,100 observations before discarding all but the newest per country:
-- 340 ms. Picking the newest row first and joining the descriptive tables to the
-- ~194 survivors is 3x quicker. indicator_code sits inside the DISTINCT ON so a
-- caller's `where indicator_code = ...` still reaches the scan.
create or replace view v_latest_observations as
select
    latest.country_code,
    cp.country_name,
    cp.region,
    cp.income_classification,
    latest.indicator_code,
    ic.indicator_name,
    ic.category,
    ic.unit,
    ic.frequency,
    ic.concept,
    ic.metric_type,
    ic.transformation,
    ic.observation_basis,
    ic.price_basis,
    ic.coverage_definition,
    ic.seasonal_adjustment,
    ic.is_primary_for_concept,
    ic.comparability_notes,
    ds.name as source,
    latest.observation_date,
    latest.value,
    latest.is_validated,
    latest.ingested_at
from (
    select distinct on (ts.country_code, ic0.indicator_code)
        ts.country_code,
        ic0.indicator_code,
        ts.indicator_id,
        ts.source_id,
        ts.date as observation_date,
        ts.value,
        ts.is_validated,
        ts.ingested_at
    from time_series ts
    join indicators_catalog ic0 on ic0.id = ts.indicator_id
    where ts.value is not null
    order by ts.country_code, ic0.indicator_code, ts.date desc
) latest
join indicators_catalog ic on ic.id = latest.indicator_id
join data_sources ds on ds.id = latest.source_id
left join country_profiles cp on cp.country_code = latest.country_code;

comment on view v_latest_observations is
    'The most recent non-null observation per (country, indicator). "Most recent" is
     per series, not as of a common date — coverage genuinely differs, and forcing a
     shared cut-off would silently drop countries from a global ranking. The
     observation date travels with every row so a stale reading is visible rather
     than implied.';

-- ── the index the ranking query needs ────────────────────────
-- time_series_natural_key leads on country_code, which serves "this country's
-- history" and does nothing for "every country on this indicator" — the ranking
-- shape. Measured on the live database before and after, ranking all countries on
-- GGXWDG_NGDP: 2,122 ms -> 70 ms execution, 304 ms -> 66 ms planning. Costs ~9 MB
-- across the 72 partitions.
create index if not exists time_series_indicator_country_date_idx
    on time_series (indicator_id, country_code, date desc);
