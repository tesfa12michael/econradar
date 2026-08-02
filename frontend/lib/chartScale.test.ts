import { describe, expect, it } from 'vitest';

import { niceDomain } from './chartScale';

describe('niceDomain', () => {
  /* The case this exists for: Recharts' own rounding put the floor at -45 for
   * Ghana's inflation, whose minimum is -8.42, spending a fifth of the plot on
   * empty space below the line. */
  it('rounds outward to a step a reader recognises', () => {
    expect(niceDomain([-8.42, 122.9, 14.2])).toEqual([-25, 125]);
  });

  it('does not force a baseline of zero', () => {
    // A policy rate between 4% and 7.75% anchored at zero is a flat line. A
    // line chart encodes position, not length, so the baseline is free.
    const [low] = niceDomain([4, 7.75, 5.5])!;
    expect(low).toBeGreaterThan(0);
  });

  it('always contains every value it was given', () => {
    for (const values of [
      [4, 7.75],
      [-8.42, 122.9],
      [0.13, 34.2],
      [231.4, 108_450],
      [-26.4, 43.6],
    ]) {
      const [low, high] = niceDomain(values)!;
      expect(low).toBeLessThanOrEqual(Math.min(...values));
      expect(high).toBeGreaterThanOrEqual(Math.max(...values));
    }
  });

  it('gives a flat series somewhere to sit rather than a zero-height axis', () => {
    const [low, high] = niceDomain([5, 5, 5])!;
    expect(high).toBeGreaterThan(low);
  });

  it('returns nothing when there is nothing to scale', () => {
    expect(niceDomain([])).toBeUndefined();
    expect(niceDomain([Number.NaN, Number.POSITIVE_INFINITY])).toBeUndefined();
  });
});
