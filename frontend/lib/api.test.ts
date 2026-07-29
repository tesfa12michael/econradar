import { afterEach, describe, expect, it } from 'vitest';

import { apiBaseUrl, apiUrl, DEFAULT_API_URL, formatValue, sourceLabel } from './api';

describe('api url helpers', () => {
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_API_URL;
  });

  it('falls back to the default when the env var is unset', () => {
    expect(apiBaseUrl()).toBe(DEFAULT_API_URL);
    expect(apiUrl('/health')).toBe(`${DEFAULT_API_URL}/health`);
  });

  it('uses the env var and trims a trailing slash', () => {
    process.env.NEXT_PUBLIC_API_URL = 'https://api.example.com/';
    expect(apiBaseUrl()).toBe('https://api.example.com');
    expect(apiUrl('health')).toBe('https://api.example.com/health');
  });
});

describe('formatValue', () => {
  it('shows missing data as text, never as a number', () => {
    expect(formatValue(null)).toBe('No data');
    expect(formatValue(undefined)).toBe('No data');
    expect(formatValue(NaN)).toBe('No data');
  });

  it('distinguishes a real zero from missing data', () => {
    expect(formatValue(0, '%')).toBe('0.00%');
  });

  it('applies unit affixes', () => {
    expect(formatValue(3.2, '%')).toBe('3.20%');
    expect(formatValue(1500, 'US$')).toBe('$1,500');
    expect(formatValue(4.25, 'LCU/US$')).toBe('4.25 LCU/US$');
  });

  it('scales precision to magnitude', () => {
    expect(formatValue(12345.6)).toBe('12,346');
    expect(formatValue(1.234)).toBe('1.23');
  });

  it('handles negatives', () => {
    expect(formatValue(-23.4, '%')).toBe('-23.4%');
  });
});

describe('sourceLabel', () => {
  it('maps data_sources names to display labels', () => {
    expect(sourceLabel('world_bank')).toBe('World Bank');
    expect(sourceLabel('wb_databank')).toBe('WB DataBank');
    expect(sourceLabel('bis')).toBe('BIS');
  });

  it('falls back to the raw name and handles null', () => {
    expect(sourceLabel('something_new')).toBe('something_new');
    expect(sourceLabel(null)).toBe('Unknown');
  });
});
