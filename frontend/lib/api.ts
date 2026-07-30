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

export interface Narration {
  country_code: string;
  indicator_code: string;
  text: string;
  provider: string;
  model: string;
  /** The verifier's verdict on this exact text, recorded when it was generated. */
  groundedness_score: number | null;
  cached: boolean;
}

export interface ChartInterpretation extends Narration {}

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
  groq: 'Groq',
  openrouter: 'OpenRouter',
  gemini_flash: 'Gemini Flash',
  qwen3_vl_openrouter: 'Qwen3-VL',
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
