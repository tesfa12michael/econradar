import { describe, expect, it } from 'vitest';

import { elapsedLabel, placeSources } from './freshness';
import type { SourceHealth } from './api';

const NOW = Date.parse('2026-08-08T12:00:00Z');

function source(name: string, lastRun: string | null, isActive = true): SourceHealth {
  return { name, is_active: isActive, last_successful_run: lastRun };
}

describe('elapsedLabel', () => {
  it('names the absence rather than printing a zero', () => {
    // A connector that has never succeeded is not "0 days ago". That reading
    // would put it at the fresh end of the scale, which is the opposite of true.
    expect(elapsedLabel(null, NOW)).toBe('no successful run on record');
  });

  it('reads in days once past two days', () => {
    expect(elapsedLabel('2026-08-02T07:00:29Z', NOW)).toBe('6 days ago');
  });

  it('keeps hours legible inside the first two days', () => {
    expect(elapsedLabel('2026-08-07T12:00:00Z', NOW)).toBe('24 hr ago');
    expect(elapsedLabel('2026-08-08T09:30:00Z', NOW)).toBe('2 hr ago');
  });

  it('never renders a negative interval when clocks disagree', () => {
    // The database's clock running ahead of the renderer's must not produce
    // "in -3 hours" on a page whose whole job is being trusted.
    expect(elapsedLabel('2026-08-08T15:00:00Z', NOW)).toBe('just now');
  });

  it('says so when the timestamp cannot be read', () => {
    expect(elapsedLabel('not a date', NOW)).toBe('unreadable timestamp');
  });
});

describe('placeSources', () => {
  const sources = [
    source('bis', '2026-08-02T07:00:29Z'),
    source('fred', '2026-08-05T06:01:55Z'),
    source('imf', '2026-08-03T05:01:49Z'),
  ];

  it('puts the oldest run at the left edge and render time at the right', () => {
    const { sources: placed } = placeSources(sources, NOW);
    expect(placed.find((s) => s.name === 'bis')!.at).toBe(0);
    // Nothing reaches 1: the right edge is now, and nothing ran at exactly now.
    for (const item of placed) expect(item.at!).toBeLessThan(1);
  });

  it('orders positions the same way the timestamps order', () => {
    const placed = placeSources(sources, NOW).sources;
    const bis = placed.find((s) => s.name === 'bis')!.at!;
    const imf = placed.find((s) => s.name === 'imf')!.at!;
    const fred = placed.find((s) => s.name === 'fred')!.at!;
    expect(bis).toBeLessThan(imf);
    expect(imf).toBeLessThan(fred);
  });

  it('gives a source that never ran no position at all', () => {
    const placed = placeSources([...sources, source('wb_databank', null)], NOW).sources;
    expect(placed.find((s) => s.name === 'wb_databank')!.at).toBeNull();
  });

  it('keeps a readable span when every source is current', () => {
    // All five running minutes ago must not collapse the axis to a single pixel.
    const fresh = [source('a', '2026-08-08T11:59:00Z'), source('b', '2026-08-08T11:58:00Z')];
    const placed = placeSources(fresh, NOW).sources;
    expect(placed[0].at).toBeGreaterThan(0.9);
    expect(placed[0].at).toBeLessThanOrEqual(1);
  });

  it('survives having no sources at all', () => {
    const { sources: placed, from } = placeSources([], NOW);
    expect(placed).toEqual([]);
    expect(from).toBeNull();
  });
});
