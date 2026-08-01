-- ─────────────────────────────────────────────────────────────
-- 0011_indicator_metadata.sql — what each indicator actually measures
--
-- The catalog knew an indicator's name, unit and frequency. It did not know
-- whether a number was year-over-year or month-over-month, an annual average or
-- a year-end stock, nominal or real, general government or central government,
-- an ILO-modelled estimate or a national definition. Nothing in the database
-- could tell those apart, so nothing downstream could either — which is how a
-- model comes to compare an IMF general-government debt ratio with a World Bank
-- central-government one and present the difference as news.
--
-- Every value below was read from the provider's own metadata on 2026-08-01, not
-- inferred from the indicator name. The probes are recorded in PROGRESS.md; two
-- of them changed an answer we would otherwise have guessed wrong:
--   * BIS WS_CBPOL's own TITLE says "Monthly - End of period", not an average.
--   * The World Bank now publishes CPTOTSAXNZGY as "CPI Price, % y-o-y, nominal,
--     seas. adj." — the stored name says "not seas. adj.", an older label. The N
--     distinguishes *nominal* from the M (median-weighted) variant; it does not
--     mean "not adjusted".
--
-- Additive and idempotent. Nothing is dropped, no existing column changes type,
-- and the connectors' catalog upsert touches only indicator_name/unit/frequency,
-- so ingestion cannot overwrite any of this.
-- ─────────────────────────────────────────────────────────────

alter table indicators_catalog
    add column if not exists concept                text,
    add column if not exists metric_type            text,
    add column if not exists transformation         text,
    add column if not exists observation_basis      text,
    add column if not exists price_basis            text,
    add column if not exists coverage_definition    text,
    add column if not exists seasonal_adjustment    text,
    add column if not exists is_primary_for_concept boolean not null default false,
    add column if not exists comparability_notes    text;

comment on column indicators_catalog.concept is
    'What is being measured, independent of who measures it — "unemployment",
     "government_debt". Several indicators may share a concept and still not be
     interchangeable; that is exactly what the qualifier columns are for. An open
     taxonomy, deliberately unconstrained, because a new source brings new concepts.';
comment on column indicators_catalog.metric_type is
    'The kind of number: a percentage change, a share of GDP, a rate, an index level,
     a currency amount. Two indicators with different metric_type must never be
     compared to each other.';
comment on column indicators_catalog.transformation is
    'How the series is derived over time — year_over_year, month_over_month, or none
     for a level. The MoM/YoY confusion this exists to prevent is the single easiest
     way to be wrong about inflation by an order of magnitude.';
comment on column indicators_catalog.observation_basis is
    'What one observation represents: an average over the period, the value at its
     end, or a total accumulated across it. A year-end debt stock and an annual
     average inflation rate are both "annual" and are not the same kind of number.';
comment on column indicators_catalog.price_basis is
    'nominal | real | ppp | not_applicable. No PPP series is currently ingested, so a
     question about PPP GDP has no answer here and must be told so.';
comment on column indicators_catalog.coverage_definition is
    'Whose definition, and how much of the sector: ILO-modelled against national,
     general government against central government. Two of the four unemployment and
     debt series in this catalog differ *only* on this column.';
comment on column indicators_catalog.is_primary_for_concept is
    'The series to use when a question names a concept but not an indicator. Chosen on
     cross-country comparability and coverage, never on recency — a ranking is only
     meaningful if every country in it was measured the same way.';
comment on column indicators_catalog.comparability_notes is
    'What a reader has to know before putting this number beside another one. Written
     to be quoted, because it travels with the value into an answer.';

-- Closed vocabularies. NULL stays legal so a newly-ingested indicator is not
-- rejected at the door, but it is not silent either: a backend test fails when any
-- indicator holding observations has unclassified metadata.
alter table indicators_catalog drop constraint if exists indicators_catalog_metric_type_ck;
alter table indicators_catalog add constraint indicators_catalog_metric_type_ck
    check (metric_type is null or metric_type in (
        'percent_change', 'percent_of_gdp', 'percent_of_labor_force',
        'rate', 'index', 'currency_level', 'currency_per_capita', 'exchange_rate'));

alter table indicators_catalog drop constraint if exists indicators_catalog_transformation_ck;
alter table indicators_catalog add constraint indicators_catalog_transformation_ck
    check (transformation is null or transformation in (
        'none', 'year_over_year', 'month_over_month', 'quarter_over_quarter'));

alter table indicators_catalog drop constraint if exists indicators_catalog_observation_basis_ck;
alter table indicators_catalog add constraint indicators_catalog_observation_basis_ck
    check (observation_basis is null or observation_basis in (
        'period_average', 'end_of_period', 'period_total', 'point_in_time'));

alter table indicators_catalog drop constraint if exists indicators_catalog_price_basis_ck;
alter table indicators_catalog add constraint indicators_catalog_price_basis_ck
    check (price_basis is null or price_basis in ('nominal', 'real', 'ppp', 'not_applicable'));

alter table indicators_catalog drop constraint if exists indicators_catalog_coverage_ck;
alter table indicators_catalog add constraint indicators_catalog_coverage_ck
    check (coverage_definition is null or coverage_definition in (
        'ilo_modelled', 'national_definition', 'oecd_harmonised',
        'general_government', 'central_government', 'not_applicable'));

alter table indicators_catalog drop constraint if exists indicators_catalog_seasonal_ck;
alter table indicators_catalog add constraint indicators_catalog_seasonal_ck
    check (seasonal_adjustment is null or seasonal_adjustment in (
        'seasonally_adjusted', 'not_seasonally_adjusted', 'not_applicable'));

-- Exactly one primary per concept, enforced rather than intended: two primaries
-- would make "which country has the highest X" answerable two different ways.
create unique index if not exists indicators_catalog_one_primary_per_concept
    on indicators_catalog (concept) where is_primary_for_concept;

-- ── backfill ─────────────────────────────────────────────────
-- Keyed on (source, indicator_code): indicator codes are unique per source, not
-- globally, and a future collision must not silently classify the wrong row.
with meta(source, code, concept, metric_type, transformation, observation_basis,
          price_basis, coverage_definition, seasonal_adjustment, is_primary, notes) as (values

-- ── GDP growth ──
('world_bank', 'NY.GDP.MKTP.KD.ZG', 'gdp_growth', 'percent_change', 'year_over_year',
 'period_total', 'real', 'not_applicable', 'not_applicable', true,
 'Annual growth of GDP at constant 2015 prices in US dollars — a real rate, so inflation is already removed. Not comparable with nominal growth figures. Covers 214 countries, which is why it is the default for a cross-country growth ranking.'),
('imf', 'NGDP_RPCH', 'gdp_growth', 'percent_change', 'year_over_year',
 'period_total', 'real', 'not_applicable', 'not_applicable', false,
 'IMF World Economic Outlook (April 2026 vintage) real GDP growth. Values for the current and following years are IMF staff projections, not outturns — always read the observation date before describing one as what happened.'),

-- ── inflation and the price level ──
('world_bank', 'FP.CPI.TOTL.ZG', 'inflation', 'percent_change', 'year_over_year',
 'period_average', 'nominal', 'not_applicable', 'not_applicable', true,
 'Annual average consumer price inflation: this year''s average CPI against last year''s, not December against December. A full-year figure, so it lags a monthly reading at a turning point and will differ from it.'),
('imf', 'PCPIPCH', 'inflation', 'percent_change', 'year_over_year',
 'period_average', 'nominal', 'not_applicable', 'not_applicable', false,
 'IMF WEO average consumer price inflation — period average, not end of period (WEO publishes that separately as PCPIEPCH, which is not ingested here). Current-year values are staff projections.'),
('wb_databank', 'CPTOTSAXNZGY', 'inflation', 'percent_change', 'year_over_year',
 'period_average', 'nominal', 'not_applicable', 'seasonally_adjusted', false,
 'Monthly inflation measured year-on-year — each month against the same month a year earlier, NOT against the previous month. Seasonally adjusted, nominal terms. This is the series to quote for a current inflation reading; the annual World Bank and IMF figures are full-year averages and will not match it.'),
('fred', 'FRED.CPI', 'price_level', 'index', 'none',
 'period_average', 'nominal', 'not_applicable', 'seasonally_adjusted', true,
 'An index LEVEL with 1982-84 = 100, not an inflation rate. A value of 320 means prices are 3.2x their 1982-84 average; it is meaningless to compare against a percentage. United States only.'),

-- ── GDP per capita ──
('world_bank', 'NY.GDP.PCAP.CD', 'gdp_per_capita', 'currency_per_capita', 'none',
 'period_total', 'nominal', 'not_applicable', 'not_applicable', true,
 'Current-price GDP per head converted at market exchange rates. NOT purchasing-power-parity — no PPP series is ingested, so PPP-adjusted comparisons cannot be made from this database. Market-rate figures understate living standards where local prices are low.'),
('imf', 'NGDPDPC', 'gdp_per_capita', 'currency_per_capita', 'none',
 'period_total', 'nominal', 'not_applicable', 'not_applicable', false,
 'IMF WEO GDP per capita at current prices and market exchange rates, not PPP. Current-year values are staff projections.'),

-- ── unemployment ──
('world_bank', 'SL.UEM.TOTL.ZS', 'unemployment', 'percent_of_labor_force', 'none',
 'period_average', 'not_applicable', 'ilo_modelled', 'not_applicable', true,
 'Modelled ILO estimate — harmonised by the ILO to one definition across 187 countries, which is what makes a global ranking meaningful. It is an estimate and can differ from the figure a national statistics office publishes.'),
('imf', 'LUR', 'unemployment', 'percent_of_labor_force', 'none',
 'period_average', 'not_applicable', 'national_definition', 'not_applicable', false,
 'National definition as reported to the IMF, so countries are NOT measured the same way and this series must not be used to rank them against each other. Covers 118 countries. Current-year values are staff projections.'),
('fred', 'FRED.UNRATE', 'unemployment', 'percent_of_labor_force', 'none',
 'period_average', 'not_applicable', 'oecd_harmonised', 'seasonally_adjusted', false,
 'Monthly and seasonally adjusted, three countries only (US, Germany, Japan). The US series is the BLS household-survey rate; Germany and Japan use the OECD harmonised rate, which applies the same ILO definition. A monthly reading, so it will not equal the annual average for the same year.'),

-- ── government debt ──
('imf', 'GGXWDG_NGDP', 'government_debt', 'percent_of_gdp', 'none',
 'end_of_period', 'nominal', 'general_government', 'not_applicable', true,
 'GENERAL government gross debt — central, state and local government together, plus social security funds. This is the standard basis for a debt-to-GDP comparison and covers 194 countries. Substantially larger than the central-government-only measure for any federal state. A year-end stock, not a flow. Current-year values are IMF staff projections.'),
('world_bank', 'GC.DOD.TOTL.GD.ZS', 'government_debt', 'percent_of_gdp', 'none',
 'end_of_period', 'nominal', 'central_government', 'not_applicable', false,
 'CENTRAL government debt only — excludes state, local and social security debt, so it is systematically lower than the general-government measure and the two must never be compared or mixed in one ranking. Covers 109 countries. Measured as a stock on the last day of the fiscal year.'),

-- ── external accounts ──
('world_bank', 'BN.CAB.XOKA.GD.ZS', 'current_account', 'percent_of_gdp', 'none',
 'period_total', 'nominal', 'not_applicable', 'not_applicable', true,
 'Current account balance as a share of GDP, accumulated across the year. Negative means a deficit. Covers 200 countries.'),
('imf', 'BCA_NGDPD', 'current_account', 'percent_of_gdp', 'none',
 'period_total', 'nominal', 'not_applicable', 'not_applicable', false,
 'IMF WEO current account balance as a share of GDP. Current-year values are staff projections.'),
('world_bank', 'NE.EXP.GNFS.ZS', 'exports', 'percent_of_gdp', 'none',
 'period_total', 'nominal', 'not_applicable', 'not_applicable', true,
 'Exports of goods and services as a share of GDP. Can legitimately exceed 100% for a re-export economy, so a high value is not an error.'),
('world_bank', 'NE.IMP.GNFS.ZS', 'imports', 'percent_of_gdp', 'none',
 'period_total', 'nominal', 'not_applicable', 'not_applicable', true,
 'Imports of goods and services as a share of GDP. Can legitimately exceed 100% for a re-export economy.'),

-- ── rates ──
('bis', 'CBPOL', 'policy_rate', 'rate', 'none',
 'end_of_period', 'not_applicable', 'not_applicable', 'not_applicable', true,
 'Central bank policy rate at END of month, per BIS''s own series title — not a monthly average. 48 reporting central banks. Readings from a hyperinflation era are nominal annualised rates under currencies that in several cases no longer exist, and are not on the same scale as post-stabilisation levels.'),
('fred', 'FRED.POLRATE', 'policy_rate', 'rate', 'none',
 'period_average', 'not_applicable', 'not_applicable', 'not_applicable', false,
 'US effective federal funds rate, averaged over the month rather than taken at month end — so it will not equal the BIS end-of-month policy rate for the same month even though both describe the same instrument. United States only.'),
('fred', 'FRED.GOV10Y', 'bond_yield', 'rate', 'none',
 'period_average', 'not_applicable', 'oecd_harmonised', 'not_applicable', true,
 'Ten-year government bond yield, OECD-harmonised monthly series so the four countries (US, Germany, UK, Japan) are like for like. A monthly average of daily yields.'),

-- ── World Bank Global Economic Monitor, monthly ──
('wb_databank', 'DPANUSSPB', 'exchange_rate', 'exchange_rate', 'none',
 'period_average', 'nominal', 'not_applicable', 'not_applicable', true,
 'Local currency units per US dollar, averaged over the month. A RISING value means the local currency is weakening. Historical values are restated in the current currency where a redenomination occurred.'),
('wb_databank', 'IPTOTSAKD', 'industrial_production', 'currency_level', 'none',
 'period_total', 'real', 'not_applicable', 'seasonally_adjusted', true,
 'Industrial output in constant 2005 US dollars, seasonally adjusted — a level, not a growth rate. Covers manufacturing, mining and utilities only, so it is not a measure of the whole economy.'),
('wb_databank', 'DSTKMKTXD', 'equity_market', 'index', 'none',
 'end_of_period', 'nominal', 'not_applicable', 'not_applicable', true,
 'Local equity market index valued in US dollars, so it moves with the exchange rate as well as with share prices. Index levels are not comparable ACROSS countries — each has its own base — only against the same country''s own history.')

)
update indicators_catalog ic
   set concept                = m.concept,
       metric_type            = m.metric_type,
       transformation         = m.transformation,
       observation_basis      = m.observation_basis,
       price_basis            = m.price_basis,
       coverage_definition    = m.coverage_definition,
       seasonal_adjustment    = m.seasonal_adjustment,
       is_primary_for_concept = m.is_primary,
       comparability_notes    = m.notes
  from meta m
  join data_sources ds on ds.name = m.source
 where ic.source_id = ds.id
   and ic.indicator_code = m.code;
