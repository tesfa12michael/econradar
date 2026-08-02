import { ArrowLeft } from '@phosphor-icons/react/dist/ssr';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { AnomalyExplanationsPanel, ChartAnalysisPanel } from '@/components/AiPanel';
import { ForecastChart } from '@/components/ForecastChart';
import { SiteFooter } from '@/components/home/SiteFooter';
import { TopBar } from '@/components/home/TopBar';
import { CountryLink, Empty, Figure, Meta, SectionHead, SourceMark } from '@/components/primitives';
import {
  basisSummary,
  fetchJson,
  formatValue,
  indicatorTitle,
  sourceLabel,
  yearOf,
  type AnomalyRecord,
  type CountryProfile,
  type IndicatorMetadata,
  type IndicatorSeries,
  type IndicatorSummary,
  type Ranking,
  type SystemStatus,
} from '@/lib/api';
import { orderForCountry, summarise, type SeriesStats } from '@/lib/series';

export const revalidate = 300;

interface PageProps {
  params: Promise<{ code: string }>;
  searchParams: Promise<{ indicator?: string }>;
}

export async function generateMetadata({ params }: PageProps) {
  const { code } = await params;
  const iso3 = code.toUpperCase();
  const countries = await fetchJson<CountryProfile[]>('/api/v1/countries');
  const name = countries?.find((c) => c.country_code === iso3)?.country_name;
  return { title: name ?? iso3 };
}

export default async function CountryPage({ params, searchParams }: PageProps) {
  const { code } = await params;
  const { indicator } = await searchParams;
  const iso3 = code.toUpperCase();
  if (iso3.length !== 3 || !/^[A-Z]+$/.test(iso3)) notFound();

  const [held, catalogue, countries, status] = await Promise.all([
    fetchJson<IndicatorSummary[]>(`/api/v1/indicators/${iso3}`),
    fetchJson<IndicatorMetadata[]>('/api/v1/indicator-metadata'),
    fetchJson<CountryProfile[]>('/api/v1/countries'),
    fetchJson<SystemStatus>('/status'),
  ]);

  const profile = countries?.find((c) => c.country_code === iso3);

  if (!held || held.length === 0) {
    return <NoDataShell iso3={iso3} name={profile?.country_name} status={status} />;
  }

  /* The API returns a country's series sorted by indicator code, which puts the
   * IMF current-account balance at the head of every profile. Ordering by
   * coverage with primaries first opens on GDP or inflation instead. */
  const ordered = orderForCountry(held, catalogue ?? []);
  const known = new Set(ordered.map((m) => m.indicator_code));
  const selected = indicator && known.has(indicator) ? indicator : ordered[0].indicator_code;

  const [series, anomalies, ranking] = await Promise.all([
    fetchJson<IndicatorSeries>(
      `/api/v1/indicators/${iso3}?code=${encodeURIComponent(selected)}`,
    ),
    fetchJson<AnomalyRecord[]>(
      `/api/v1/anomalies?country=${iso3}&indicator=${encodeURIComponent(selected)}&limit=50`,
    ),
    fetchJson<Ranking>(`/api/v1/rankings/${encodeURIComponent(selected)}?limit=300&order=desc`),
  ]);

  const meta =
    ranking?.indicator ?? catalogue?.find((m) => m.indicator_code === selected) ?? null;
  const flagged = anomalies ?? [];
  const stats = summarise(series?.observations ?? []);
  const rank = ranking?.entries.find((e) => e.country_code === iso3) ?? null;
  const name = profile?.country_name ?? series?.country_name ?? iso3;
  const hasData = Boolean(series && series.observations.some((o) => o.value !== null));

  return (
    <>
      <TopBar status={status?.status ?? null} />

      <main id="main" className="mx-auto max-w-6xl px-5 pb-4 pt-8 sm:px-6">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 rounded-sm text-[13px] text-ink-muted transition-colors duration-200 hover:text-signal"
        >
          <ArrowLeft aria-hidden weight="bold" className="size-3.5" />
          Map
        </Link>

        <header className="mt-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          {/* The ISO-3 code rather than `country_profiles.flag_emoji`. A flag
              emoji is a pair of regional-indicator characters, and a platform
              without the glyph falls back to rendering the two letters — so on
              Windows this line read "GH Ghana" at forty-eight pixels, which
              looks like a bug. The code is the identifier the rest of the
              product already uses, in citations and in the map readout, and it
              renders identically everywhere. */}
          <h1 className="flex items-baseline gap-3 text-[clamp(2rem,4.4vw,3rem)] font-medium leading-none tracking-[-0.03em]">
            <span
              data-numeric
              aria-hidden
              className="text-[0.4em] tracking-[0.16em] text-ink-dim"
            >
              {iso3}
            </span>
            {name}
          </h1>
          <Meta className="pb-1 text-ink-muted">
            {[profile?.imf_classification, profile?.region, profile?.income_classification]
              .filter(Boolean)
              .join(' · ')}
          </Meta>
        </header>

        <SeriesRail options={ordered} selected={selected} iso3={iso3} />

        {/* ── The measurement, then the chart. Which series this is and how it
            is defined has to come before the picture of it: a reader who does
            not know that "unemployment" here is a modelled ILO estimate cannot
            tell whether the line means what they think. ───────────────────── */}
        <section aria-labelledby="series-heading" className="mt-9">
          <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-3">
            <div className="min-w-0">
              <h2
                id="series-heading"
                className="text-[clamp(1.15rem,2vw,1.5rem)] font-medium leading-tight tracking-[-0.02em] text-ink"
              >
                {indicatorTitle(series?.indicator_name ?? meta?.indicator_name) || selected}
              </h2>
              <p className="mt-2">
                <Meta className="text-ink-muted">
                  {meta?.country_count ? `${meta.country_count} countries · ` : ''}
                  {stats.firstDate ? `${yearOf(stats.firstDate)}-${yearOf(stats.lastDate)} · ` : ''}
                  {sourceLabel(series?.source ?? meta?.source)}
                  {meta && basisSummary(meta).length > 0 && ` · ${basisSummary(meta).join(' · ')}`}
                </Meta>
              </p>
            </div>

            {rank && ranking && (
              <Link
                href={`/?indicator=${encodeURIComponent(selected)}`}
                className="group shrink-0 rounded-md text-right"
                title="See this series on the world map"
              >
                <Figure size="lg" className="transition-colors duration-200 group-hover:text-signal">
                  {rank.rank}
                </Figure>
                <Meta className="ml-1">of {ranking.country_count}</Meta>
                <p>
                  <Meta>ranked worldwide</Meta>
                </p>
              </Link>
            )}
          </div>

          <div className="mt-6">
            {hasData ? (
              /* Keyed on the indicator so switching tabs remounts the overlay
                 and the in-flight forecast request aborts rather than racing
                 the new one. */
              <ForecastChart
                key={selected}
                countryCode={iso3}
                indicator={selected}
                observations={series!.observations}
                anomalies={flagged}
                unit={series!.unit}
                indicatorName={series!.indicator_name}
                stats={stats}
              />
            ) : (
              <Empty
                title="No observations for this series"
                hint="This country and series combination holds nothing in the database. The other series above are unaffected."
              />
            )}
          </div>
        </section>

        {hasData && (
          <div className="mt-12 grid gap-x-14 gap-y-10 lg:grid-cols-[minmax(0,0.72fr)_minmax(0,1fr)]">
            {/* Context: what this measurement is and what it can be compared
                with. The note is written by whoever publishes the series. */}
            {/* `lg:pt-5` matches the insight card's own padding, so the two
                column headings sit on the same line instead of the card's
                border pushing its heading twenty pixels lower than its
                neighbour. */}
            <aside aria-labelledby="basis-heading" className="lg:order-1 lg:pt-5">
              <SectionHead title={<span id="basis-heading">What is being measured</span>} />
              <div className="mt-3 space-y-3">
                {meta?.comparability_notes ? (
                  <p className="max-w-[46ch] text-[13px] leading-[1.7] text-ink-muted">
                    {meta.comparability_notes}
                  </p>
                ) : (
                  <Meta className="block">
                    No measurement note is recorded for this series.
                  </Meta>
                )}
                <dl className="space-y-1.5 border-t border-[color:var(--hairline)] pt-3">
                  <Fact label="Source" value={sourceLabel(series?.source ?? meta?.source)} />
                  {meta?.frequency && <Fact label="Frequency" value={meta.frequency} />}
                  {meta?.observation_count != null && (
                    <Fact
                      label="Observations held"
                      value={meta.observation_count.toLocaleString('en-US')}
                      hint="across every country"
                    />
                  )}
                  <Fact
                    label="This country"
                    value={`${stats.count} observations`}
                    hint={
                      stats.firstDate
                        ? `${yearOf(stats.firstDate)}-${yearOf(stats.lastDate)}`
                        : undefined
                    }
                  />
                </dl>
                <SourceMark source={series?.source ?? meta?.source} className="pt-1" />
              </div>
            </aside>

            <div className="space-y-12 lg:order-2">
              <ChartAnalysisPanel key={`v-${selected}`} countryCode={iso3} indicator={selected} />
              {flagged.length > 0 && (
                <AnomalyExplanationsPanel
                  key={`a-${selected}`}
                  countryCode={iso3}
                  indicator={selected}
                />
              )}
            </div>
          </div>
        )}

        <section aria-labelledby="other-heading" className="mt-16">
          <SectionHead
            title={<span id="other-heading">Everything else held for {name}</span>}
            meta={<Meta>{ordered.length} series · latest reading each</Meta>}
          />
          <ul className="mt-4 grid gap-x-10 sm:grid-cols-2 lg:grid-cols-3">
            {ordered
              .filter((m) => m.indicator_code !== selected)
              .map((m) => (
                <li
                  key={m.indicator_code}
                  className="border-t border-[color:var(--hairline)] py-2.5"
                >
                  <Link
                    href={`/country/${iso3}?indicator=${encodeURIComponent(m.indicator_code)}`}
                    className="group flex items-baseline justify-between gap-3 rounded-sm"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] text-ink-muted transition-colors duration-200 group-hover:text-signal">
                        {indicatorTitle(m.indicator_name)}
                      </span>
                      <Meta>{m.latest_date?.slice(0, 7) ?? 'undated'}</Meta>
                    </span>
                    <span data-numeric className="shrink-0 text-[13px] text-ink">
                      {formatValue(m.latest_value, m.unit)}
                    </span>
                  </Link>
                </li>
              ))}
          </ul>
        </section>
      </main>

      <SiteFooter sources={status?.sources ?? []} />
    </>
  );
}

function Fact({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt>
        <Meta>{label}</Meta>
      </dt>
      <dd className="text-right">
        <Meta className="text-ink-muted">{value}</Meta>
        {hint && (
          <>
            {' '}
            <Meta>{hint}</Meta>
          </>
        )}
      </dd>
    </div>
  );
}

/** The series this country holds, ordered by coverage with primaries first.
 *
 * Server-rendered links, not a JavaScript control: switching series has worked
 * without JavaScript since Phase 2 and is one of the few guarantees this
 * frontend makes. They are set as an index rather than as bordered pills —
 * sixteen buttons in a block is a wall, sixteen quiet links with one of them
 * lit is a list you can read.
 */
const RAIL_VISIBLE = 10;

function SeriesRail({
  options,
  selected,
  iso3,
}: {
  options: IndicatorSummary[];
  selected: string;
  iso3: string;
}) {
  const shown = options.slice(0, RAIL_VISIBLE);
  const rest = options.slice(RAIL_VISIBLE);
  // Open on arrival if what is being plotted lives in the hidden half, so the
  // page never highlights a series the reader cannot see.
  const restHoldsSelected = rest.some((o) => o.indicator_code === selected);

  return (
    <nav aria-label="Series held for this country" className="mt-7">
      <SeriesLinks options={shown} selected={selected} iso3={iso3} className="border-t pt-3" />

      {/* Japan holds twenty-one series, which is four rows of links before the
          chart even starts. A native disclosure keeps the rail to two rows and
          keeps switching series working without JavaScript, which it has done
          since Phase 2. */}
      {rest.length > 0 && (
        <details open={restHoldsSelected} className="group mt-2">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-sm text-[12px] text-ink-dim transition-colors duration-200 hover:text-ink [&::-webkit-details-marker]:hidden">
            <span aria-hidden className="transition-transform duration-200 group-open:rotate-90">
              ›
            </span>
            <span data-numeric>{rest.length}</span> more
          </summary>
          <SeriesLinks options={rest} selected={selected} iso3={iso3} className="mt-2.5" />
        </details>
      )}
    </nav>
  );
}

function SeriesLinks({
  options,
  selected,
  iso3,
  className,
}: {
  options: IndicatorSummary[];
  selected: string;
  iso3: string;
  className?: string;
}) {
  return (
    <ul
      className={`flex flex-wrap gap-x-5 gap-y-2 border-[color:var(--hairline)] ${className ?? ''}`}
    >
      {options.map((option) => {
        const active = option.indicator_code === selected;
        return (
          <li key={option.indicator_code}>
            <Link
              href={`/country/${iso3}?indicator=${encodeURIComponent(option.indicator_code)}`}
              aria-current={active ? 'page' : undefined}
              className={[
                'rounded-sm text-[13px] transition-colors duration-200',
                active
                  ? 'text-signal underline decoration-[color:var(--signal)] decoration-1 underline-offset-[6px]'
                  : 'text-ink-dim hover:text-ink',
              ].join(' ')}
            >
              {indicatorTitle(option.indicator_name)}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function NoDataShell({
  iso3,
  name,
  status,
}: {
  iso3: string;
  name?: string;
  status: SystemStatus | null;
}) {
  return (
    <>
      <TopBar status={status?.status ?? null} />
      <main id="main" className="mx-auto flex min-h-[60vh] max-w-3xl flex-col justify-center gap-5 px-5 sm:px-6">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 self-start rounded-sm text-[13px] text-ink-muted transition-colors duration-200 hover:text-signal"
        >
          <ArrowLeft aria-hidden weight="bold" className="size-3.5" />
          Map
        </Link>
        <h1 className="flex items-baseline gap-3 text-[clamp(1.6rem,3.4vw,2.25rem)] font-medium tracking-[-0.03em]">
          <span data-numeric aria-hidden className="text-[0.42em] tracking-[0.16em] text-ink-dim">
            {iso3}
          </span>
          {name ?? iso3}
        </h1>
        <Empty
          className="py-0"
          title="Nothing is held for this country"
          hint="No source currently enabled publishes a series for it. This is a gap in this dataset, not a statement about the country."
        />
        <p>
          <CountryLink code="JPN" className="text-[13px] text-signal">
            Open a country that has data
          </CountryLink>
        </p>
      </main>
      <SiteFooter sources={status?.sources ?? []} />
    </>
  );
}

export type { SeriesStats };
