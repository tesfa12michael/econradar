/** Where the whole field stands on the indicator on screen.
 *
 * This reads `GET /api/v1/rankings`, which had no reader on the frontend at
 * all — and it exists because of the single most instructive failure in this
 * project's history. Asked which country had the highest debt-to-GDP, an
 * earlier retrieval-based answer said **Montenegro**: a real figure, correctly
 * quoted, and wrong about 193 other countries, because a superlative is a claim
 * about a dataset and retrieval is definitionally a subset. (Montenegro is rank
 * 75 of 194.)
 *
 * So the ranking always reads every country, and the rail shows the fold —
 * five at the top, three at the bottom, and an explicit count of everything
 * between them. A top-five list that hides its denominator is the same mistake
 * in a nicer typeface.
 */

import { RevealGroup, RevealItem } from '@/components/motion/Reveal';
import { CountryLink, Empty, Meta, SectionHead } from '@/components/primitives';
import { formatValue, type Ranking, type RankingEntry } from '@/lib/api';

const TOP = 5;
const BOTTOM = 3;

export function RankingRail({
  ranking,
  indicatorName,
}: {
  ranking: Ranking | null;
  indicatorName: string | null;
}) {
  if (!ranking || ranking.entries.length === 0) {
    return (
      <section aria-labelledby="ranking-heading">
        <SectionHead title={<span id="ranking-heading">Ranked worldwide</span>} />
        <Empty
          title="This series is not ranked"
          hint={`${indicatorName ?? 'This indicator'} has no cross-country ranking — usually because the countries in it are not measured the same way, which makes a league table of them misleading rather than merely imprecise.`}
        />
      </section>
    );
  }

  const { entries, country_count: total, indicator } = ranking;
  const top = entries.slice(0, TOP);
  const bottom = entries.length > TOP + BOTTOM ? entries.slice(-BOTTOM) : [];
  const between = entries.length - top.length - bottom.length;

  return (
    <section aria-labelledby="ranking-heading">
      <SectionHead
        title={<span id="ranking-heading">Ranked worldwide</span>}
        meta={<Meta>{total} countries · latest reading each</Meta>}
      />

      <RevealGroup className="mt-3" step={0.03}>
        {top.map((entry) => (
          <RevealItem key={entry.country_code}>
            <Row entry={entry} unit={indicator.unit} code={indicator.indicator_code} />
          </RevealItem>
        ))}

        {bottom.length > 0 && (
          <RevealItem>
            {/* The fold. This is the part a top-five list normally hides. */}
            <div className="flex items-center gap-3 py-3" aria-hidden>
              <span className="h-px flex-1 bg-[color:var(--hairline)]" />
              <Meta>{between} between</Meta>
              <span className="h-px flex-1 bg-[color:var(--hairline)]" />
            </div>
          </RevealItem>
        )}

        {bottom.map((entry) => (
          <RevealItem key={entry.country_code}>
            <Row entry={entry} unit={indicator.unit} code={indicator.indicator_code} />
          </RevealItem>
        ))}
      </RevealGroup>

      {/* Two things a reader has to be told rather than left to assume: the
          dates are not all the same year, and the ranking has a definition. */}
      {ranking.earliest_observation && ranking.latest_observation && (
        <p className="mt-3 border-t border-[color:var(--hairline)] pt-2.5">
          <Meta className="leading-relaxed">
            Readings span {ranking.earliest_observation.slice(0, 4)}-
            {ranking.latest_observation.slice(0, 4)}; each country is ranked on its most
            recent, so a stale figure can outrank a current one.
          </Meta>
        </p>
      )}
    </section>
  );
}

function Row({
  entry,
  unit,
  code,
}: {
  entry: RankingEntry;
  unit: string | null;
  code: string;
}) {
  return (
    /* A leader rule between the name and the figure, the way a statistical
     * annex sets a table. Without it the eye has to cross 300px of nothing to
     * pair a country with its number, and the two read as separate columns
     * rather than one row. */
    <div className="grid grid-cols-[2rem_auto_minmax(1.5rem,1fr)_auto] items-center gap-x-3 py-[7px]">
      <Meta className="text-right text-ink-muted">{entry.rank}</Meta>
      <CountryLink
        code={entry.country_code}
        name={entry.country_name}
        indicator={code}
        className="truncate text-[13px]"
      />
      <span aria-hidden className="h-px bg-[color:var(--hairline)]" />
      <span className="flex items-baseline gap-2.5">
        <span data-numeric className="text-[13px] text-ink">
          {formatValue(entry.value, unit)}
        </span>
        <Meta className="w-8 text-right">{entry.observation_date?.slice(0, 4) ?? '—'}</Meta>
      </span>
    </div>
  );
}
