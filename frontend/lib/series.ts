/** Facts about a series that the page states rather than implies.
 *
 * All of it is computed from the observations already fetched for the chart —
 * no extra request, and no number that is not in the plotted data.
 */

import type { IndicatorMetadata, Observation } from './api';

export interface SeriesStats {
  latest: { value: number; date: string } | null;
  min: { value: number; date: string } | null;
  max: { value: number; date: string } | null;
  /** Observations carrying a value. Gaps are excluded, not counted as zero. */
  count: number;
  firstDate: string | null;
  lastDate: string | null;
}

export function summarise(observations: Observation[]): SeriesStats {
  const points = observations
    .filter((o): o is Observation & { value: number } => o.value !== null && Number.isFinite(o.value))
    .sort((a, b) => a.date.localeCompare(b.date));

  if (points.length === 0) {
    return { latest: null, min: null, max: null, count: 0, firstDate: null, lastDate: null };
  }

  let min = points[0];
  let max = points[0];
  for (const point of points) {
    if (point.value < min.value) min = point;
    if (point.value > max.value) max = point;
  }

  const last = points[points.length - 1];
  return {
    latest: { value: last.value, date: last.date },
    min: { value: min.value, date: min.date },
    max: { value: max.value, date: max.date },
    count: points.length,
    firstDate: points[0].date,
    lastDate: last.date,
  };
}

/** Order the series a country holds so the useful ones come first.
 *
 * The API returns them sorted by indicator code, which puts `BCA_NGDPD` — the
 * IMF's current-account balance — at the head of every country page, so that is
 * what a visitor to Ghana currently sees first. Ranking by how much of the world
 * a series covers, with the primary series for each concept ahead of its
 * alternatives, puts GDP, inflation and unemployment at the front instead.
 */
export function orderForCountry<T extends { indicator_code: string }>(
  held: T[],
  catalogue: IndicatorMetadata[],
): T[] {
  const rank = new Map<string, number>();
  catalogue.forEach((meta) => {
    // Primaries sort ahead of every alternative, then by coverage.
    const score = (meta.is_primary_for_concept ? 1_000_000 : 0) + (meta.country_count ?? 0);
    rank.set(meta.indicator_code, score);
  });
  return [...held].sort(
    (a, b) => (rank.get(b.indicator_code) ?? -1) - (rank.get(a.indicator_code) ?? -1),
  );
}
