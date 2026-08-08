/** How long ago each connector last succeeded, and where that sits on a shared axis.
 *
 * Freshness is the actual subject of the status page. "Operational" describes the
 * process; it says nothing about whether the five connectors behind the data have
 * run this week. Those are different failure modes, and the second one is invisible
 * unless the page draws it — a backend can answer every request perfectly while
 * serving figures nobody has refreshed in a month.
 *
 * Pure functions, so the arithmetic that decides what a reader is told is testable
 * without rendering anything.
 */

import type { SourceHealth } from '@/lib/api';

const DAY = 86_400_000;

/** Minimum axis span, so a system whose sources all ran in the last hour still gets
 * a readable scale instead of five dots stacked on one pixel. */
const MIN_SPAN = DAY;

/** Elapsed time in words, coarsest useful unit first.
 *
 * Rendered on the server and sent as a finished string. The absolute UTC stamp
 * beside it stays the authoritative value — this one exists because "2 Aug 07:00z"
 * means nothing to a reader who does not know today's date, and "6 days ago" is the
 * number that tells them whether to worry. Its drift is bounded by the page's
 * revalidate window.
 */
export function elapsedLabel(iso: string | null | undefined, now: number): string {
  if (!iso) return 'no successful run on record';
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return 'unreadable timestamp';

  const ms = now - at;
  // Clock skew between the database and this renderer should never produce
  // "in -3 hours". Anything at or ahead of now reads as current.
  if (ms < 60_000) return 'just now';

  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes} min ago`;

  const hours = Math.floor(ms / 3_600_000);
  if (hours < 48) return `${hours} hr ago`;

  return `${Math.floor(ms / DAY)} days ago`;
}

export interface PlacedSource {
  name: string;
  isActive: boolean;
  lastRun: string | null;
  elapsed: string;
  /** Position across the axis, 0 at the oldest run and 1 at render time. `null`
   * when the source has never succeeded, which is an absence rather than a
   * position — plotting it at zero would draw it as merely very old. */
  at: number | null;
}

export interface Freshness {
  sources: PlacedSource[];
  /** Left edge of the axis: the oldest successful run being shown. */
  from: string | null;
  /** Right edge: when this page was rendered. Not "now" — the page is cached, so
   * the honest label is the moment it last looked. */
  to: string;
}

/** Lay the sources out on one shared time axis.
 *
 * The shared axis is the whole point. Five separate "last run" strings make the
 * reader do the comparison in their head; one axis makes a connector that has
 * fallen behind the others impossible to miss.
 */
export function placeSources(sources: SourceHealth[], now: number): Freshness {
  const times = sources
    .map((source) => new Date(source.last_successful_run ?? '').getTime())
    .filter((time) => Number.isFinite(time));

  const oldest = times.length > 0 ? Math.min(...times) : now;
  const span = Math.max(now - oldest, MIN_SPAN);
  const start = now - span;

  return {
    from: times.length > 0 ? new Date(oldest).toISOString() : null,
    to: new Date(now).toISOString(),
    sources: sources.map((source) => {
      const iso = source.last_successful_run;
      const at = new Date(iso ?? '').getTime();
      return {
        name: source.name,
        isActive: source.is_active,
        lastRun: iso,
        elapsed: elapsedLabel(iso, now),
        at: Number.isFinite(at) ? clamp01((at - start) / span) : null,
      };
    }),
  };
}

function clamp01(value: number): number {
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}
