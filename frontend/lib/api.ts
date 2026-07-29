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
