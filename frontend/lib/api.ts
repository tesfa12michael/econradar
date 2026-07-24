/** Backend API URL helpers. Single source of truth for where the FastAPI backend lives. */

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
