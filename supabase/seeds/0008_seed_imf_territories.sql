-- ─────────────────────────────────────────────────────────────
-- 0008_seed_imf_territories.sql — economies the IMF tracks under its own codes
--
-- Seed 0005 is generated from the World Bank country registry, so three real
-- economies the IMF reports on are absent from it:
--
--   TWN  Taiwan                — not in the World Bank registry at all
--   WBG  West Bank and Gaza    — the World Bank uses PSE for the same economy
--   UVK  Kosovo                — ISO 3166-1 assigns XKX; the World Bank uses XKX
--
-- These are **countries, not aggregates**. Without rows here they look like
-- unrecognised codes to anything that treats country_profiles as the authoritative
-- country list, and they would render nameless on the dashboard.
--
-- Note the deliberate duplication: WBG/UVK describe the same economies as any
-- PSE/XKX rows, under the IMF's codes. Cross-source code reconciliation is a
-- known Phase 5 concern (feature 3.2's precedence rule); until then keeping both
-- is preferable to silently dropping IMF observations.
--
-- Idempotent (safe to re-run).
-- ─────────────────────────────────────────────────────────────

insert into country_profiles
    (country_code, country_name, region, income_classification, imf_classification, flag_emoji)
values
    ('TWN', 'Taiwan, Province of China', 'East Asia & Pacific', 'High income', 'Advanced', '🇹🇼'),
    ('WBG', 'West Bank and Gaza', 'Middle East, North Africa, Afghanistan & Pakistan', 'Lower middle income', 'Developing', '🇵🇸'),
    ('UVK', 'Kosovo', 'Europe & Central Asia', 'Upper middle income', 'Emerging', '🇽🇰')
on conflict (country_code) do nothing;
