import { AnomalyStream } from '@/components/home/AnomalyStream';
import { IndicatorInstrument } from '@/components/home/IndicatorInstrument';
import { LiveTape, type TapeItem } from '@/components/home/LiveTape';
import { RankingRail } from '@/components/home/RankingRail';
import { SiteFooter } from '@/components/home/SiteFooter';
import { TopBar } from '@/components/home/TopBar';
import { Empty, Meta } from '@/components/primitives';
import { WorldMap } from '@/components/WorldMap';
import {
  fetchJson,
  formatUtc,
  formatValue,
  sourceLabel,
  type AnomalyRecord,
  type IndicatorMetadata,
  type MapData,
  type Ranking,
  type SystemStatus,
} from '@/lib/api';

export const revalidate = 300;

/** GDP growth rather than whichever series happens to sort first. It has the
 * widest coverage of any indicator held (214 countries), it is signed — so the
 * map opens on a diverging scale showing real structure instead of one ramp
 * from pale to bright — and it is the figure a general reader already has a
 * feel for. */
const DEFAULT_INDICATOR = 'NY.GDP.MKTP.KD.ZG';

interface PageProps {
  searchParams: Promise<{ indicator?: string }>;
}

export default async function Home({ searchParams }: PageProps) {
  const { indicator } = await searchParams;

  const [catalogue, status] = await Promise.all([
    fetchJson<IndicatorMetadata[]>('/api/v1/indicator-metadata'),
    fetchJson<SystemStatus>('/status'),
  ]);

  const series = catalogue ?? [];
  const known = new Set(series.map((m) => m.indicator_code));
  const selected = indicator && known.has(indicator) ? indicator : DEFAULT_INDICATOR;

  const [map, anomalies, ranking] = await Promise.all([
    fetchJson<MapData>(`/api/v1/map?indicator=${encodeURIComponent(selected)}`),
    // Over-fetched because the feed keeps one reading per series (see
    // `topFlagged`), and a policy-rate decision month can flag a dozen
    // countries at once.
    fetchJson<AnomalyRecord[]>('/api/v1/anomalies?limit=60'),
    // The whole field, not a top five: the rail needs both ends and the map's
    // hover panel needs every country's rank. One request covers all three.
    fetchJson<Ranking>(`/api/v1/rankings/${encodeURIComponent(selected)}?limit=300&order=desc`),
  ]);

  const meta = ranking?.indicator ?? series.find((m) => m.indicator_code === selected) ?? null;

  const ranks: Record<string, { rank: number; of: number }> = {};
  for (const entry of ranking?.entries ?? []) {
    ranks[entry.country_code] = { rank: entry.rank, of: ranking!.country_count };
  }

  return (
    <>
      <TopBar status={status?.status ?? null} />
      <LiveTape items={buildTape(status, ranking)} />

      <main id="main">
        <section aria-labelledby="map-heading" className="relative">
          <h1 id="map-heading" className="sr-only">
            World map of {map?.indicator_name ?? selected}
          </h1>

          {/* On a wide screen this sits over the north Atlantic, where the
              choropleth has nothing to say, and reads as the caption block of a
              chart in a statistical publication. Below `lg` it stacks above the
              map instead, because overlaying a paragraph on a small map makes
              both unreadable. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-y-0 left-0 hidden w-[46%] lg:block"
            style={{
              background:
                'linear-gradient(to right, var(--plane-0) 4%, rgb(10 15 30 / 0.72) 42%, transparent 100%)',
            }}
          />

          <div className="relative px-5 pt-6 sm:px-6 lg:pointer-events-none lg:absolute lg:inset-x-0 lg:top-0 lg:z-[var(--z-raised)] lg:pt-8">
            <div className="max-w-[38rem] lg:pointer-events-auto">
              {series.length > 0 ? (
                <IndicatorInstrument
                  catalogue={series}
                  selected={selected}
                  selectedName={map?.indicator_name ?? null}
                />
              ) : (
                <p className="text-[clamp(1.5rem,3.1vw,2.35rem)] font-medium leading-[1.08] tracking-[-0.025em]">
                  {map?.indicator_name ?? 'EconRadar'}
                </p>
              )}

              {/* Written by the people who publish the series, stored per
                  indicator, and the single most useful sentence on the page:
                  it is what stops a reader comparing two things that are not
                  comparable. */}
              {meta?.comparability_notes && (
                <p className="mt-4 max-w-[54ch] text-[12.5px] leading-[1.65] text-ink-muted">
                  {meta.comparability_notes}
                </p>
              )}
            </div>
          </div>

          {map && map.points.length > 0 ? (
            <WorldMap
              points={map.points}
              indicatorCode={selected}
              indicatorName={map.indicator_name}
              unit={map.unit}
              source={map.source}
              ranks={ranks}
            />
          ) : (
            <div className="flex h-[clamp(30rem,66vh,48rem)] items-center justify-center px-6">
              <Empty
                title="No map for this series"
                hint="The backend returned nothing for this indicator. It may not have been ingested yet, or the API may be unreachable."
              />
            </div>
          )}
        </section>

        {/* Measured rather than full-bleed. The map takes the whole width
            because it is a picture of the world; what follows is read, and a
            reading column under a full-bleed plate is how a publication is
            laid out. The two columns are deliberately unequal — a ranking is
            eight short rows, a feed is ten two-line ones. */}
        <div className="mx-auto grid max-w-6xl gap-x-14 gap-y-12 px-5 pt-14 sm:px-6 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1fr)]">
          <RankingRail ranking={ranking} indicatorName={map?.indicator_name ?? null} />
          <div className="lg:border-l lg:border-[color:var(--hairline)] lg:pl-14">
            <AnomalyStream
              anomalies={topFlagged(anomalies ?? [])}
              total={status?.anomalies_flagged ?? null}
            />
          </div>
        </div>
      </main>

      <SiteFooter sources={status?.sources ?? []} />
    </>
  );
}

/** One reading per series, most severe first.
 *
 * The endpoint orders by magnitude across the whole store, which means a single
 * month of central-bank decisions can take most of the feed and the same
 * country's policy rate can appear three times. Showing South Africa's policy
 * rate twice is not two facts, so each `(country, indicator)` pair keeps only
 * its most severe reading. The ordering is untouched, and the heading says
 * exactly this — a feed that quietly reshapes what it is showing is the small
 * kind of lie this product cannot afford.
 */
function topFlagged(anomalies: AnomalyRecord[], limit = 9): AnomalyRecord[] {
  const seen = new Set<string>();
  const kept: AnomalyRecord[] = [];
  for (const anomaly of anomalies) {
    const key = `${anomaly.country_code}:${anomaly.indicator_code}`;
    if (seen.has(key)) continue;
    seen.add(key);
    kept.push(anomaly);
    if (kept.length === limit) break;
  }
  return kept;
}

/** The tape's contents. Every item is a figure the system currently holds or a
 * timestamp of when it last pulled from a source — no headlines, nothing
 * invented, nothing standing in for a feed that does not exist. */
function buildTape(status: SystemStatus | null, ranking: Ranking | null): TapeItem[] {
  const items: TapeItem[] = [];
  const count = (n: number) => n.toLocaleString('en-US');

  if (status) {
    items.push(
      { label: 'observations', value: count(status.observations_tracked) },
      { label: 'countries', value: count(status.countries_tracked) },
      { label: 'series', value: count(status.indicators_tracked) },
      { label: 'flagged', value: count(status.anomalies_flagged) },
    );
  }

  const first = ranking?.entries[0];
  const last = ranking?.entries[ranking.entries.length - 1];
  if (first && last && ranking) {
    const unit = ranking.indicator.unit;
    const code = ranking.indicator.indicator_code;
    items.push(
      {
        label: `highest of ${ranking.country_count}`,
        value: `${first.country_name ?? first.country_code} ${formatValue(first.value, unit)}`,
        href: `/country/${first.country_code}?indicator=${encodeURIComponent(code)}`,
        live: true,
      },
      {
        label: 'lowest',
        value: `${last.country_name ?? last.country_code} ${formatValue(last.value, unit)}`,
        href: `/country/${last.country_code}?indicator=${encodeURIComponent(code)}`,
        live: true,
      },
    );
  }

  for (const source of status?.sources ?? []) {
    items.push({
      label: sourceLabel(source.name),
      value: formatUtc(source.last_successful_run),
    });
  }

  return items;
}
