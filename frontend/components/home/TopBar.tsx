import Link from 'next/link';
import { ArrowUpRight } from '@phosphor-icons/react/dist/ssr';

import { Magnetic } from '@/components/motion/Magnetic';
import { Meta } from '@/components/primitives';

/** Navigation only, and only here — the map needs the full width, so there is
 * no sidebar anywhere on this route.
 *
 * The dot beside the wordmark reports the backend's actual `/status` value. It
 * is the one status indicator in the product and it is wired to something real;
 * a decorative light that is always green is worse than no light at all. */
export function TopBar({ status }: { status: string | null }) {
  const operational = status === 'operational';

  return (
    <header className="sticky top-0 z-[var(--z-sticky)] border-b border-[color:var(--hairline)] bg-[color:var(--plane-0)]/85 backdrop-blur-xl">
      <div className="flex h-[3.75rem] items-center justify-between gap-4 px-5 sm:px-6">
        <Link href="/" className="group flex items-center gap-2.5 rounded-sm">
          <span className="text-[15px] font-medium tracking-[-0.02em] text-ink">EconRadar</span>
          <span className="flex items-center gap-1.5" title={`Backend reports: ${status ?? 'unreachable'}`}>
            <span
              aria-hidden
              className="size-1.5 rounded-full"
              style={{
                background: operational ? 'var(--positive)' : 'var(--alert)',
                boxShadow: `0 0 7px ${operational ? 'var(--positive)' : 'var(--alert)'}`,
              }}
            />
            <Meta className="hidden uppercase tracking-[0.16em] text-ink-muted sm:inline">
              {operational ? 'live' : status ?? 'offline'}
            </Meta>
          </span>
        </Link>

        <nav className="flex items-center gap-1" aria-label="Primary">
          <Link
            href="/status"
            className="rounded-md px-3 py-1.5 text-[13px] text-ink-muted transition-colors duration-200 hover:bg-[color:var(--plane-2)] hover:text-ink"
          >
            Status
          </Link>
          <Magnetic strength={4}>
            <Link
              href="/chat"
              className="group flex items-center gap-1.5 rounded-md border border-[color:var(--edge-strong)] px-3.5 py-1.5 text-[13px] font-medium text-ink transition-colors duration-200 hover:border-[color:var(--signal)] hover:text-signal"
            >
              Ask the data
              <ArrowUpRight
                aria-hidden
                weight="bold"
                className="size-3.5 text-ink-dim transition-colors duration-200 group-hover:text-signal"
              />
            </Link>
          </Magnetic>
        </nav>
      </div>
    </header>
  );
}
