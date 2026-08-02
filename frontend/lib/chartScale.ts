/** Axis scaling and labelling for the time-series chart.
 *
 * Pure, and kept out of the chart component so it can be tested without
 * rendering Recharts.
 */

const STEPS = [1, 2, 2.5, 5, 10];

/** Axis bounds rounded outward to a step a reader recognises.
 *
 * Recharts' own domain rounds to whole tick intervals of its choosing, which on
 * Ghana's inflation put the floor at -45 against a series minimum of -8.42: a
 * fifth of the plot height spent below the line. Choosing the step from the
 * data's own range gives -25 to 125 instead — round ticks, and the chart back
 * at full height.
 *
 * **The baseline is not forced to zero, and that is deliberate.** Zero-anchoring
 * is required of bar charts, where the length of the bar encodes the value. A
 * line encodes position, so anchoring a policy rate that moves between 4% and
 * 8% to zero would flatten every move it makes into a straight line — hiding
 * the data rather than presenting it honestly.
 */
export function niceDomain(values: number[]): [number, number] | undefined {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return undefined;

  const low = Math.min(...finite);
  const high = Math.max(...finite);
  const range = high - low;

  if (range === 0) {
    const pad = Math.abs(low) * 0.1 || 1;
    return [low - pad, high + pad];
  }

  const target = range / 6;
  const magnitude = Math.pow(10, Math.floor(Math.log10(target)));
  const step = (STEPS.find((m) => target <= m * magnitude) ?? 10) * magnitude;
  return [Math.floor(low / step) * step, Math.ceil(high / step) * step];
}

/** Axis labels, short enough to read at eleven pixels.
 *
 * The precision comes from the axis's own span rather than from each value, so
 * one tick cannot print more decimals than its neighbours — an axis reading
 * "-25, 5.0, 35" is the sort of detail that makes a chart look unfinished. The
 * series here run from policy rates near 4 to GDP per capita above 100,000, so
 * the large end is abbreviated rather than spelled out into the plot area.
 */
export function axisTicker(span: number) {
  const decimals = span >= 12 ? 0 : span >= 1.5 ? 1 : 2;
  return (value: number): string => {
    if (!Number.isFinite(value)) return '';
    const magnitude = Math.abs(value);
    if (magnitude >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (magnitude >= 1_000) return `${(value / 1_000).toFixed(magnitude >= 10_000 ? 0 : 1)}k`;
    return value.toFixed(decimals);
  };
}
