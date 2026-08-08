import { Meta } from '@/components/primitives';
import { RevealGroup, RevealItem } from '@/components/motion/Reveal';
import { formatUtc, sourceLabel } from '@/lib/api';
import type { Freshness as FreshnessData } from '@/lib/freshness';

/** The five connectors on one shared time axis.
 *
 * The reason this is a picture rather than a list: five separate "last run"
 * timestamps make the reader do the comparison in their head, and the comparison is
 * the entire point. On one axis, a connector that has fallen days behind the others
 * is visible before you have read a single label.
 *
 * Position is the only variable carrying meaning here. The filled segment restates
 * it as length because two encodings of the same fact are easier to scan than one,
 * and nothing is encoded by colour alone: every row carries its own timestamp and
 * its elapsed interval in words.
 */
export function Freshness({ data }: { data: FreshnessData }) {
  if (data.sources.length === 0) {
    return (
      <Meta>
        The backend answered, and listed no data sources at all. That is a fault
        rather than an empty state: the observations above came from somewhere.
      </Meta>
    );
  }

  return (
    <div>
      <RevealGroup className="space-y-px">
        {data.sources.map((source) => (
          <RevealItem key={source.name}>
            <div className="grid items-center gap-x-4 gap-y-1 py-2.5 sm:grid-cols-[7.5rem_minmax(0,1fr)_auto]">
              <span className="text-[13px] text-ink">{sourceLabel(source.name)}</span>

              {/* Presentational: every value plotted here is also written in the
                  row, so the axis adds legibility and never carries a fact alone. */}
              <span aria-hidden className="relative block h-4 sm:h-3">
                {/* Centred with `my-auto` rather than `-translate-y-1/2`: the
                    draw-in keyframe animates `transform`, and a transform-based
                    centring would be overwritten by it — leaving the fill half a
                    pixel off its own track for good, since the fill persists. */}
                <span className="absolute inset-x-0 inset-y-0 my-auto h-px bg-[color:var(--hairline)]" />

                {source.at !== null && (
                  <>
                    <span
                      className="absolute inset-y-0 left-0 my-auto h-px origin-left bg-[color:var(--signal-dim)]"
                      style={{
                        width: `${source.at * 100}%`,
                        animation: 'draw-x var(--dur-5) var(--ease-out) both',
                      }}
                    />
                    <span
                      className="absolute top-1/2 size-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full"
                      style={{
                        left: `${source.at * 100}%`,
                        background: source.isActive ? 'var(--signal)' : 'var(--alert)',
                        boxShadow: `0 0 8px ${source.isActive ? 'var(--signal-wash)' : 'var(--alert)'}`,
                      }}
                    />
                  </>
                )}
              </span>

              {/* Two aligned columns rather than one flowing line. Mono keeps the
                  stamps a fixed width; giving the interval its own right-aligned
                  column stops "5 Aug 06:01z 3 days ago" reading as one string. */}
              <span className="flex items-baseline gap-5 sm:justify-end">
                <Meta className="text-ink-muted">{formatUtc(source.lastRun)}</Meta>
                <Meta className="sm:inline-block sm:w-[6.25rem] sm:text-right">
                  {source.elapsed}
                </Meta>
                {!source.isActive && <Meta className="text-alert">disabled</Meta>}
              </span>
            </div>
          </RevealItem>
        ))}
      </RevealGroup>

      {/* Both ends of the axis, labelled. The right edge is genuinely now: the
          elapsed intervals are computed against the clock at render, and the
          timestamps they are measured from are fixed facts that do not decay
          while the payload sits in a cache. */}
      <div className="mt-1 hidden items-baseline justify-between border-t border-[color:var(--hairline)] pt-2 sm:flex sm:pl-[8.5rem]">
        <Meta>{data.from ? formatUtc(data.from) : ''}</Meta>
        <Meta>now</Meta>
      </div>
    </div>
  );
}
