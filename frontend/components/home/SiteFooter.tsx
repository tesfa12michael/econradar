import Link from 'next/link';

import { Meta } from '@/components/primitives';
import { formatUtc, sourceLabel, type SourceHealth } from '@/lib/api';

/** Provenance, in the place a publication puts it.
 *
 * Each of the five agencies is listed with the last time EconRadar successfully
 * pulled from it, because "our data is live" is a claim and a timestamp is
 * evidence. `/status` is linked from here, which is where the design system
 * says it should be reachable from.
 */
export function SiteFooter({ sources }: { sources: SourceHealth[] }) {
  return (
    <footer className="mt-20 border-t border-[color:var(--hairline)]">
      <div className="mx-auto grid max-w-7xl gap-8 px-5 py-9 sm:px-6 md:grid-cols-[1fr_auto]">
        <div>
          <h2 className="text-[13px] font-medium text-ink">Ingested from</h2>
          <ul className="mt-3 grid gap-x-10 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
            {sources.map((source) => (
              <li
                key={source.name}
                className="flex max-w-[15rem] items-baseline justify-between gap-3"
              >
                <Meta className="text-ink-muted">{sourceLabel(source.name)}</Meta>
                <Meta>{formatUtc(source.last_successful_run)}</Meta>
              </li>
            ))}
          </ul>
        </div>

        <div className="flex flex-col items-start gap-2 md:items-end">
          <nav className="flex items-center gap-4" aria-label="Secondary">
            <Link
              href="/chat"
              className="rounded-sm text-[13px] text-ink-muted transition-colors duration-200 hover:text-ink"
            >
              Ask the data
            </Link>
            <Link
              href="/status"
              className="rounded-sm text-[13px] text-ink-muted transition-colors duration-200 hover:text-ink"
            >
              Status
            </Link>
            <a
              href="https://github.com/tesfa12michael/econradar"
              className="rounded-sm text-[13px] text-ink-muted transition-colors duration-200 hover:text-ink"
            >
              Source
            </a>
          </nav>
          <Meta className="max-w-[36ch] md:text-right">
            Forecasts are model output, not observations. Figures written by a model are
            checked against the records they came from before they are shown.
          </Meta>
        </div>
      </div>
    </footer>
  );
}
