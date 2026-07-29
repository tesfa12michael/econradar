import { describe, expect, it } from 'vitest';

import {
  buildDomain,
  colorFor,
  legendStops,
  NO_DATA_COLOR,
  rgbToCss,
  scaleTypeFor,
} from './colorScale';

describe('scaleTypeFor', () => {
  it('uses a diverging ramp for signed indicators', () => {
    expect(scaleTypeFor('NY.GDP.MKTP.KD.ZG')).toBe('diverging');
    expect(scaleTypeFor('BN.CAB.XOKA.GD.ZS')).toBe('diverging');
  });

  it('uses a sequential ramp otherwise', () => {
    expect(scaleTypeFor('NY.GDP.PCAP.CD')).toBe('sequential');
  });
});

describe('buildDomain', () => {
  it('centres a diverging domain on zero so neutral means no change', () => {
    const d = buildDomain([-4, -2, 0, 1, 9], 'NY.GDP.MKTP.KD.ZG');
    expect(d.type).toBe('diverging');
    expect(d.min).toBe(-d.max);
  });

  it('clips outliers so one extreme does not flatten the rest', () => {
    const normal = Array.from({ length: 40 }, (_, i) => i);
    const d = buildDomain([...normal, 1_000_000], 'NY.GDP.PCAP.CD');
    expect(d.max).toBeLessThan(1000);
  });

  it('survives an empty series without producing a zero-width domain', () => {
    const d = buildDomain([], 'NY.GDP.PCAP.CD');
    expect(d.max).toBeGreaterThan(d.min);
  });

  it('never produces a zero-width domain when every value is identical', () => {
    const d = buildDomain([5, 5, 5], 'NY.GDP.PCAP.CD');
    expect(d.max).toBeGreaterThan(d.min);
  });
});

describe('colorFor', () => {
  const domain = buildDomain([0, 50, 100], 'NY.GDP.PCAP.CD');

  it('renders missing data distinctly, never as a low value', () => {
    expect(colorFor(null, domain)).toEqual(NO_DATA_COLOR);
    expect(colorFor(undefined, domain)).toEqual(NO_DATA_COLOR);
    expect(colorFor(NaN, domain)).toEqual(NO_DATA_COLOR);
  });

  it('distinguishes the lowest real value from no data', () => {
    // Otherwise the least-valued country reads identically to one with no data,
    // which is the false reading features.md 1.6 forbids.
    expect(colorFor(domain.min, domain)).not.toEqual(NO_DATA_COLOR);
    expect(colorFor(0, domain)).not.toEqual(colorFor(null, domain));
  });

  it('keeps the diverging neutral distinct from no data too', () => {
    const diverging = buildDomain([-5, 0, 5], 'NY.GDP.MKTP.KD.ZG');
    expect(colorFor(0, diverging)).not.toEqual(NO_DATA_COLOR);
  });

  it('clamps out-of-domain values instead of producing invalid channels', () => {
    for (const value of [-9999, 9999]) {
      const rgb = colorFor(value, domain);
      for (const channel of rgb) {
        expect(channel).toBeGreaterThanOrEqual(0);
        expect(channel).toBeLessThanOrEqual(255);
      }
    }
  });

  it('moves through the ramp as the value rises', () => {
    expect(colorFor(0, domain)).not.toEqual(colorFor(100, domain));
  });
});

describe('legendStops', () => {
  it('returns evenly spaced stops with labels', () => {
    const stops = legendStops(buildDomain([0, 100], 'NY.GDP.PCAP.CD'), 5);
    expect(stops).toHaveLength(5);
    expect(stops.every((s) => s.label.length > 0)).toBe(true);
  });
});

describe('rgbToCss', () => {
  it('formats a css rgb string', () => {
    expect(rgbToCss([0, 212, 255])).toBe('rgb(0, 212, 255)');
  });
});
