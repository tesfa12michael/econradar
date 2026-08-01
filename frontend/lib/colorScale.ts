/** Choropleth colour scales, dark-first by design.
 *
 * The design system bans inverting a light-mode palette: on a dark surface that
 * produces an unreadable neon result. These ramps are the ones specified in
 * docs/designsystem.md, and no-data countries take the card background so they
 * recede rather than reading as a low value.
 */

export type RGB = [number, number, number];

/** Sequential ramp — low to high, for single-direction indicators.
 *
 * Deliberate deviation from designsystem.md: the documented ramp *begins* at #1A2235,
 * which is also the specified no-data colour. That collision would make the
 * lowest-valued country indistinguishable from one with no data at all — exactly the
 * false reading features.md 1.6 forbids. The ramp therefore starts one stop in, at
 * #1E4080, leaving #1A2235 to mean "no data" and nothing else.
 */
const SEQUENTIAL: RGB[] = [
  [30, 64, 128], // #1E4080
  [26, 122, 191], // #1A7ABF
  [0, 168, 212], // #00A8D4
  [0, 212, 255], // #00D4FF
];

/** Diverging ramp — negative through neutral to positive (e.g. GDP growth). */
const DIVERGING: RGB[] = [
  [127, 29, 29], // #7F1D1D
  [154, 63, 58], // interpolated toward neutral
  [42, 54, 78], // near-neutral, lifted off the no-data colour so the two never match
  [5, 78, 59], // #064E3B
  [52, 211, 153], // #34D399 — positive terminus, kept legible on dark
];

/** No data. Deliberately the card background, so it recedes instead of reading as zero. */
export const NO_DATA_COLOR: RGB = [26, 34, 53];

/** Indicators that are meaningfully signed and so deserve a diverging ramp. */
const DIVERGING_CODES = new Set([
  'NY.GDP.MKTP.KD.ZG',
  'NGDP_RPCH',
  'BN.CAB.XOKA.GD.ZS',
  'BCA_NGDPD',
]);

export function scaleTypeFor(indicatorCode: string): 'sequential' | 'diverging' {
  return DIVERGING_CODES.has(indicatorCode) ? 'diverging' : 'sequential';
}

function lerp(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t);
}

function sample(ramp: RGB[], t: number): RGB {
  const clamped = Math.min(1, Math.max(0, t));
  const scaled = clamped * (ramp.length - 1);
  const index = Math.min(ramp.length - 2, Math.floor(scaled));
  const frac = scaled - index;
  const from = ramp[index];
  const to = ramp[index + 1];
  return [lerp(from[0], to[0], frac), lerp(from[1], to[1], frac), lerp(from[2], to[2], frac)];
}

export interface Domain {
  min: number;
  max: number;
  type: 'sequential' | 'diverging';
}

/** Build a colour domain from the values actually present.
 *
 * Percentile clipping (5th–95th) stops a single hyperinflation outlier from
 * flattening every other country into one indistinguishable shade.
 */
export function buildDomain(values: number[], indicatorCode: string): Domain {
  const type = scaleTypeFor(indicatorCode);
  const finite = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (finite.length === 0) return { min: 0, max: 1, type };

  const at = (p: number) => finite[Math.min(finite.length - 1, Math.floor(p * finite.length))];
  let min = at(0.05);
  let max = at(0.95);

  if (type === 'diverging') {
    // Symmetric around zero so the neutral colour genuinely means "no change".
    const bound = Math.max(Math.abs(min), Math.abs(max)) || 1;
    min = -bound;
    max = bound;
  }
  if (min === max) max = min + 1;
  return { min, max, type };
}

export function colorFor(value: number | null | undefined, domain: Domain): RGB {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_DATA_COLOR;
  const t = (value - domain.min) / (domain.max - domain.min);
  return sample(domain.type === 'diverging' ? DIVERGING : SEQUENTIAL, t);
}

export function rgbToCss(rgb: RGB): string {
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}

/** Blend two colours. Used by the map's sweep, which paints each country from
 * the no-data colour to its value as the sweep line reaches it. */
export function mixRgb(from: RGB, to: RGB, t: number): RGB {
  const clamped = Math.min(1, Math.max(0, t));
  return [
    lerp(from[0], to[0], clamped),
    lerp(from[1], to[1], clamped),
    lerp(from[2], to[2], clamped),
  ];
}

/** The ramp as a CSS gradient, so the legend shows the continuous scale the map
 * actually uses rather than a handful of sampled swatches. */
export function rampCss(domain: Domain, steps = 12): string {
  const ramp = domain.type === 'diverging' ? DIVERGING : SEQUENTIAL;
  const stops = Array.from({ length: steps }, (_, i) =>
    rgbToCss(sample(ramp, i / (steps - 1))),
  );
  return `linear-gradient(to right, ${stops.join(', ')})`;
}

/** Evenly spaced legend stops with their labels. */
export function legendStops(domain: Domain, count = 5): { color: RGB; label: string }[] {
  return Array.from({ length: count }, (_, i) => {
    const t = i / (count - 1);
    const value = domain.min + (domain.max - domain.min) * t;
    const digits = Math.abs(value) >= 100 ? 0 : 1;
    return {
      color: sample(domain.type === 'diverging' ? DIVERGING : SEQUENTIAL, t),
      label: value.toFixed(digits),
    };
  });
}
