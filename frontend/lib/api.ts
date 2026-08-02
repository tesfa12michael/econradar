/** Backend API URL helpers and response types. Single source of truth for where the
 * FastAPI backend lives and what it returns. */

export const DEFAULT_API_URL = 'http://localhost:8000';

export function apiBaseUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_URL;
  return (fromEnv && fromEnv.length > 0 ? fromEnv : DEFAULT_API_URL).replace(/\/$/, '');
}

export function apiUrl(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${apiBaseUrl()}${suffix}`;
}

export interface HealthResponse {
  status: string;
  environment: string;
  version: string;
  database: string;
  scheduler: string;
}

export interface IndicatorOption {
  indicator_code: string;
  indicator_name: string;
  category: string | null;
  unit: string | null;
  frequency: string | null;
  source: string;
  country_count: number;
}

export interface MapPoint {
  country_code: string;
  country_name: string | null;
  /** null means "no data" — never render this as zero. */
  value: number | null;
  date: string | null;
  has_anomaly: boolean;
}

export interface MapData {
  indicator_code: string;
  indicator_name: string | null;
  unit: string | null;
  source: string | null;
  points: MapPoint[];
}

export interface Observation {
  date: string;
  value: number | null;
  is_validated: boolean;
}

export interface IndicatorSeries {
  country_code: string;
  country_name: string | null;
  indicator_code: string;
  indicator_name: string | null;
  unit: string | null;
  source: string;
  observations: Observation[];
}

export interface IndicatorSummary {
  indicator_code: string;
  indicator_name: string;
  category: string | null;
  unit: string | null;
  latest_date: string | null;
  latest_value: number | null;
}

export interface AnomalyRecord {
  country_code: string;
  country_name: string | null;
  indicator_code: string;
  indicator_name: string | null;
  date: string;
  value: number | null;
  /** null for a structural break, where a Z-score is mathematically undefined. */
  z_score: number | null;
  deviation_type: string | null;
  detected_at: string | null;
}

export interface CountryProfile {
  country_code: string;
  country_name: string;
  region: string | null;
  income_classification: string | null;
  imf_classification: string | null;
  flag_emoji: string | null;
}

/* ── Phase 3 intelligence layer ───────────────────────────────────────────── */

export interface ForecastPoint {
  date: string;
  median: number;
  lower: number;
  upper: number;
}

export interface Forecast {
  country_code: string;
  indicator_code: string;
  indicator_name: string | null;
  unit: string | null;
  frequency: string | null;
  /** Which model in the cascade produced this — always shown, never inferred. */
  model_used: string;
  horizon: number;
  points: ForecastPoint[];
  cached: boolean;
  generated_at: string | null;
}

export interface ChartInterpretation {
  country_code: string;
  indicator_code: string;
  text: string;
  provider: string;
  model: string;
  /** The verifier's verdict on this exact text, recorded when it was generated. */
  groundedness_score: number | null;
  cached: boolean;
}

export interface AnomalyExplanation {
  country_code: string;
  indicator_code: string;
  date: string;
  value: number | null;
  z_score: number | null;
  deviation_type: string | null;
  /** null when no provider returned a grounded explanation — never invented. */
  explanation: string | null;
  cached: boolean;
}

/* ── Measurement metadata and rankings (features 2.8) ─────────────────────── */

/** What an indicator actually measures. Seven typed axes plus a written note,
 * populated from each provider's own metadata rather than inferred. This is the
 * layer that distinguishes the three unemployment series and the two debt
 * series from each other — mixing them produces a wrong answer that reads as
 * perfectly plausible. */
export interface IndicatorMetadata {
  indicator_code: string;
  indicator_name: string;
  source: string;
  unit: string | null;
  frequency: string | null;
  category: string | null;
  concept: string | null;
  metric_type: string | null;
  transformation: string | null;
  observation_basis: string | null;
  price_basis: string | null;
  coverage_definition: string | null;
  seasonal_adjustment: string | null;
  /** Exactly one series per concept carries this — a partial unique index, not
   * a convention, because two primaries would make "which country has the
   * highest X" answerable two different ways. */
  is_primary_for_concept: boolean;
  comparability_notes: string | null;
  country_count: number | null;
  observation_count: number | null;
  earliest_date: string | null;
  latest_date: string | null;
}

export interface RankingEntry {
  rank: number;
  country_code: string;
  country_name: string | null;
  region: string | null;
  value: number;
  observation_date: string | null;
  source: string | null;
}

/** A ranking always reads every country. `limit` trims the response after the
 * ranking is computed and counted, so `country_count` keeps reporting the whole
 * field and `truncated` says outright that it was cut. */
export interface Ranking {
  indicator: IndicatorMetadata;
  order: 'asc' | 'desc';
  country_count: number;
  truncated: boolean;
  earliest_observation: string | null;
  latest_observation: string | null;
  entries: RankingEntry[];
}

const CONCEPT_LABELS: Record<string, string> = {
  gdp_growth: 'GDP growth',
  gdp_per_capita: 'GDP per capita',
  current_account: 'Current account',
  government_debt: 'Government debt',
  exports: 'Exports',
  imports: 'Imports',
  inflation: 'Inflation',
  unemployment: 'Unemployment',
  exchange_rate: 'Exchange rate',
  industrial_production: 'Industrial production',
  equity_market: 'Equity market',
  policy_rate: 'Policy rate',
  bond_yield: 'Bond yield',
  price_level: 'Price level',
};

export function conceptLabel(concept: string | null | undefined): string {
  if (!concept) return 'Other';
  return CONCEPT_LABELS[concept] ?? concept.replace(/_/g, ' ');
}

/** Vocabulary values worth telling a reader about, in reading order.
 *
 * `not_applicable` and `none` are omitted rather than rendered: "seasonal
 * adjustment: not applicable" is noise on an annual series, and a basis line
 * that is half disclaimers stops being read at all. */
const BASIS_WORDS: Record<string, string> = {
  real: 'real',
  nominal: 'nominal',
  year_over_year: 'year-over-year',
  period_average: 'period average',
  period_total: 'period total',
  end_of_period: 'end of period',
  general_government: 'general government',
  central_government: 'central government',
  ilo_modelled: 'ILO-modelled',
  national_definition: 'national definition',
  oecd_harmonised: 'OECD-harmonised',
  seasonally_adjusted: 'seasonally adjusted',
  not_seasonally_adjusted: 'not seasonally adjusted',
};

/** The one-line answer to "what am I looking at?" */
export function basisSummary(meta: Partial<IndicatorMetadata>): string[] {
  return [
    meta.price_basis,
    meta.transformation,
    meta.observation_basis,
    meta.coverage_definition,
    meta.seasonal_adjustment,
  ]
    .map((value) => (value ? BASIS_WORDS[value] : undefined))
    .filter((value): value is string => Boolean(value));
}

/** Tidy a provider's series name for display.
 *
 * Two of the stored names end in stray commas — "CPI Price, % y-o-y, not seas.
 * adj.,," and "Exchange rate, new LCU per USD extended backward, period
 * average,," — because that is how the provider publishes them. The name is
 * left alone in the database, where it has to match the source; the trailing
 * punctuation is dropped on the way to the screen, where it just reads as a
 * typo. */
export function indicatorTitle(name: string | null | undefined): string {
  if (!name) return '';
  return name.replace(/[\s,;·-]+$/, '');
}

/** Year from an ISO date, for coverage ranges. */
export function yearOf(date: string | null | undefined): string {
  return date ? date.slice(0, 4) : '—';
}

/** An absolute UTC timestamp, formatted identically on the server and in the
 * browser.
 *
 * Deliberately not "2 hours ago". These pages are statically revalidated, so a
 * relative time is computed at build and then drifts silently for as long as
 * the cache lives — and it would differ between the server render and the
 * client's clock, which is a hydration mismatch on every page load. An absolute
 * time in UTC is one fact that stays true. */
export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return 'never';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return 'unknown';
  const day = at.getUTCDate();
  const month = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ][at.getUTCMonth()];
  const hh = String(at.getUTCHours()).padStart(2, '0');
  const mm = String(at.getUTCMinutes()).padStart(2, '0');
  return `${day} ${month} ${hh}:${mm}z`;
}

export interface SourceHealth {
  name: string;
  is_active: boolean;
  last_successful_run: string | null;
}

/** The public status payload. Sanitised aggregates only — no question text and
 * no client addresses (decision #45). */
export interface SystemStatus {
  status: string;
  environment: string;
  countries_tracked: number;
  indicators_tracked: number;
  observations_tracked: number;
  anomalies_flagged: number;
  sources: SourceHealth[];
  groundedness_verification: string;
  chat: {
    requests: number;
    outcomes: Record<string, number>;
    providers: Record<string, number>;
    cache_hit_rate: number | null;
    fallback_rate: number | null;
    ranking_rate: number | null;
    refusal_rate: number | null;
    timeout_rate: number | null;
    mean_seconds: number | null;
    tool_calls: number;
    tool_failures: number;
    tracked_clients: number;
    chat_requests_today: number;
    daily_budget: number;
    daily_remaining: number;
  } | null;
}

export interface Citation {
  index: number;
  country_code: string | null;
  country_name: string | null;
  indicator_code: string | null;
  indicator_name: string | null;
  chunk_type: string | null;
  similarity: number;
}

export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
}

/** Labels for the model that produced a forecast — the cascade is visible to the reader. */
export const MODEL_LABELS: Record<string, string> = {
  chronos2: 'Chronos-2',
  timesfm: 'TimesFM',
  statsforecast: 'StatsForecast',
};

export const PROVIDER_LABELS: Record<string, string> = {
  mistral: 'Mistral',
  // The agent runs a different Mistral model from narration, so the backend
  // registers it as its own provider (decision #39). Both read as "Mistral" here —
  // which model answered is a backend concern, not a chip.
  mistral_agent: 'Mistral',
  nvidia_nim: 'NVIDIA NIM',
  groq: 'Groq',
  openrouter: 'OpenRouter',
  gemini_flash: 'Gemini Flash',
  qwen3_vl_dashscope: 'Qwen3-VL',
};

export function modelLabel(model: string | null | undefined): string {
  if (!model) return 'unknown';
  return MODEL_LABELS[model] ?? PROVIDER_LABELS[model] ?? model;
}

/** Same-origin path for an AI endpoint (see app/api/ai/[...path]/route.ts). */
export function aiUrl(path: string): string {
  return `/api/ai/${path.replace(/^\//, '')}`;
}

/** Browser-side fetch for the async AI panels. Returns null on any failure so a
 * slow or unavailable panel never takes the page with it. */
export async function fetchAi<T>(path: string, signal?: AbortSignal): Promise<T | null> {
  try {
    const res = await fetch(aiUrl(path), { signal, cache: 'no-store' });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/** Fetch JSON, returning null rather than throwing so a slow or failed AI/data panel
 * never takes down the page around it. */
export async function fetchJson<T>(path: string, revalidate = 300): Promise<T | null> {
  try {
    const res = await fetch(apiUrl(path), { next: { revalidate } });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/** Attribution label for a data_sources.name value. */
export const SOURCE_LABELS: Record<string, string> = {
  world_bank: 'World Bank',
  wb_databank: 'WB DataBank',
  imf: 'IMF',
  fred: 'FRED',
  bis: 'BIS',
};

export function sourceLabel(source: string | null | undefined): string {
  if (!source) return 'Unknown';
  return SOURCE_LABELS[source] ?? source;
}

/** Format a value for display, preserving the "no data" distinction. */
export function formatValue(value: number | null | undefined, unit?: string | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'No data';
  const magnitude = Math.abs(value);
  const digits = magnitude >= 1000 ? 0 : magnitude >= 10 ? 1 : 2;
  const formatted = value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  if (unit === '%') return `${formatted}%`;
  if (unit === 'US$') return `$${formatted}`;
  return unit ? `${formatted} ${unit}` : formatted;
}
