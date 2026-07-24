import { afterEach, describe, expect, it } from 'vitest';

import { apiBaseUrl, apiUrl, DEFAULT_API_URL } from './api';

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
