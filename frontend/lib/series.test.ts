import { describe, expect, it } from 'vitest';

import { orderForCountry, summarise } from './series';
import type { IndicatorMetadata, Observation } from './api';

const obs = (date: string, value: number | null): Observation => ({
  date,
  value,
  is_validated: true,
});

describe('summarise', () => {
  it('reports the extremes with the dates they happened on', () => {
    const stats = summarise([
      obs('1999-01-01', 4.87),
      obs('1995-01-01', 59.5),
      obs('2025-01-01', 14.2),
    ]);
    expect(stats.min).toEqual({ value: 4.87, date: '1999-01-01' });
    expect(stats.max).toEqual({ value: 59.5, date: '1995-01-01' });
  });

  it('takes the latest by date, not by position in the response', () => {
    const stats = summarise([obs('2025-01-01', 14.2), obs('1995-01-01', 59.5)]);
    expect(stats.latest).toEqual({ value: 14.2, date: '2025-01-01' });
    expect(stats.firstDate).toBe('1995-01-01');
  });

  /* A gap is not a zero. This is the same distinction the map makes with its
   * reserved no-data colour, and getting it wrong here would report a minimum
   * of 0 for a series that never went near it. */
  it('excludes gaps rather than counting them as zero', () => {
    const stats = summarise([obs('2001-01-01', 5), obs('2002-01-01', null), obs('2003-01-01', 7)]);
    expect(stats.count).toBe(2);
    expect(stats.min?.value).toBe(5);
  });

  it('handles a series with nothing in it', () => {
    const stats = summarise([obs('2001-01-01', null)]);
    expect(stats).toEqual({
      latest: null,
      min: null,
      max: null,
      count: 0,
      firstDate: null,
      lastDate: null,
    });
  });

  it('survives a single observation', () => {
    const stats = summarise([obs('2020-01-01', 3.5)]);
    expect(stats.min).toEqual(stats.max);
    expect(stats.count).toBe(1);
  });
});

describe('orderForCountry', () => {
  const meta = (
    code: string,
    countries: number,
    primary: boolean,
  ): IndicatorMetadata =>
    ({
      indicator_code: code,
      country_count: countries,
      is_primary_for_concept: primary,
    }) as IndicatorMetadata;

  const catalogue = [
    meta('BCA_NGDPD', 196, false),
    meta('NY.GDP.MKTP.KD.ZG', 214, true),
    meta('FP.CPI.TOTL.ZG', 193, true),
  ];

  /* The API sorts a country's series by indicator code, which puts the IMF's
   * current-account balance at the top of every profile in the product. */
  it('puts a primary series ahead of a wider-covered alternative', () => {
    const ordered = orderForCountry(
      [{ indicator_code: 'BCA_NGDPD' }, { indicator_code: 'FP.CPI.TOTL.ZG' }],
      catalogue,
    );
    expect(ordered[0].indicator_code).toBe('FP.CPI.TOTL.ZG');
  });

  it('breaks ties between primaries on coverage', () => {
    const ordered = orderForCountry(
      [{ indicator_code: 'FP.CPI.TOTL.ZG' }, { indicator_code: 'NY.GDP.MKTP.KD.ZG' }],
      catalogue,
    );
    expect(ordered[0].indicator_code).toBe('NY.GDP.MKTP.KD.ZG');
  });

  it('keeps a series the catalogue does not describe rather than dropping it', () => {
    const ordered = orderForCountry(
      [{ indicator_code: 'UNKNOWN' }, { indicator_code: 'FP.CPI.TOTL.ZG' }],
      catalogue,
    );
    expect(ordered).toHaveLength(2);
    expect(ordered[1].indicator_code).toBe('UNKNOWN');
  });

  it('does not mutate the array it is given', () => {
    const held = [{ indicator_code: 'BCA_NGDPD' }, { indicator_code: 'FP.CPI.TOTL.ZG' }];
    orderForCountry(held, catalogue);
    expect(held[0].indicator_code).toBe('BCA_NGDPD');
  });
});
