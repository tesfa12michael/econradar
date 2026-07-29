-- ─────────────────────────────────────────────────────────────
-- 0004_seed_reference.sql — data_sources + indicators_catalog seed
-- Idempotent (safe to re-run). Run after the schema + partitioning.
-- Only world_bank is active in Phase 1; the other four are registered
-- but inactive until their connectors land in Phase 2.
-- ─────────────────────────────────────────────────────────────

-- Base URLs verified against the live APIs on 2026-07-29 (see docs/architecture.md
-- decisions #15-#17). Note in particular that IMF is the DataMapper REST/JSON API,
-- NOT SDMX: the SDMX endpoints return 501 "Data Queries are not implemented".
insert into data_sources (name, base_url, is_active) values
    ('world_bank',  'https://api.worldbank.org/v2',                        true),
    ('imf',         'https://www.imf.org/external/datamapper/api/v1',      false),
    ('fred',        'https://api.stlouisfed.org/fred',                     false),
    ('bis',         'https://stats.bis.org/api/v2',                        false),
    ('wb_databank', 'https://api.worldbank.org/v2',                        false)
on conflict (name) do update
    set base_url = excluded.base_url;

-- Curated World Bank annual indicators spanning macro / financial / trade / social.
-- The connector also upserts indicators it fetches, so this seed just guarantees a
-- sensible catalog exists from day one.
insert into indicators_catalog
    (source_id, indicator_code, indicator_name, category, unit, frequency, description)
select ds.id, v.code, v.name, v.category, v.unit, 'annual', v.description
from data_sources ds
cross join (values
    ('NY.GDP.MKTP.KD.ZG', 'GDP growth (annual %)',                      'macroeconomic', '%',    'Annual percentage growth rate of GDP at constant prices.'),
    ('FP.CPI.TOTL.ZG',    'Inflation, consumer prices (annual %)',      'macroeconomic', '%',    'Annual change in the cost of a basket of goods and services (CPI).'),
    ('NY.GDP.PCAP.CD',    'GDP per capita (current US$)',               'macroeconomic', 'US$',  'Gross domestic product divided by midyear population, current US dollars.'),
    ('SL.UEM.TOTL.ZS',    'Unemployment, total (% of labor force)',     'social',        '%',    'Share of the labor force that is without work but available for and seeking employment.'),
    ('NE.EXP.GNFS.ZS',    'Exports of goods and services (% of GDP)',   'trade',         '%',    'Value of all goods and services exported, as a share of GDP.'),
    ('NE.IMP.GNFS.ZS',    'Imports of goods and services (% of GDP)',   'trade',         '%',    'Value of all goods and services imported, as a share of GDP.'),
    ('GC.DOD.TOTL.GD.ZS', 'Central government debt, total (% of GDP)',  'financial',     '%',    'Total gross central government debt as a share of GDP.'),
    ('BN.CAB.XOKA.GD.ZS', 'Current account balance (% of GDP)',         'financial',     '%',    'Current account balance as a share of GDP.')
) as v(code, name, category, unit, description)
where ds.name = 'world_bank'
on conflict (source_id, indicator_code) do nothing;
