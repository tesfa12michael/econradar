import Link from 'next/link';
import { notFound } from 'next/navigation';

import {
  AnomalyExplanationsPanel,
  ChartAnalysisPanel,
  NarrationPanel,
} from '@/components/AiPanel';
import { ForecastChart } from '@/components/ForecastChart';
import { AnomalyBadge, Card, EmptyState, PanelHeading, SourceChip } from '@/components/ui';
import {
  fetchJson,
  formatValue,
  type AnomalyRecord,
  type CountryProfile,
  type IndicatorSeries,
  type IndicatorSummary,
} from '@/lib/api';

export const revalidate = 300;

interface PageProps {
  params: Promise<{ code: string }>;
  searchParams: Promise<{ indicator?: string }>;
}

export async function generateMetadata({ params }: PageProps) {
  const { code } = await params;
  return { title: `${code.toUpperCase()} — EconRadar` };
}

export default async function CountryPage({ params, searchParams }: PageProps) {
  const { code } = await params;
  const { indicator } = await searchParams;
  const iso3 = code.toUpperCase();
  if (iso3.length !== 3 || !/^[A-Z]+$/.test(iso3)) notFound();

  const available = await fetchJson<IndicatorSummary[]>(`/api/v1/indicators/${iso3}`);
  if (!available || available.length === 0) {
    return <NoDataShell iso3={iso3} />;
  }

  const selected = indicator ?? available[0].indicator_code;
  const [series, anomalies, countries] = await Promise.all([
    fetchJson<IndicatorSeries>(
      `/api/v1/indicators/${iso3}?code=${encodeURIComponent(selected)}`,
    ),
    fetchJson<AnomalyRecord[]>(
      `/api/v1/anomalies?country=${iso3}&indicator=${encodeURIComponent(selected)}&limit=50`,
    ),
    fetchJson<CountryProfile[]>('/api/v1/countries'),
  ]);

  const profile = countries?.find((c) => c.country_code === iso3);
  const name = profile?.country_name ?? series?.country_name ?? iso3;
  const flagged = anomalies ?? [];

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-5 px-6 py-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="rounded-sm text-sm underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2"
            style={{ color: 'var(--accent)', outlineColor: 'var(--accent)' }}
          >
            ← Map
          </Link>
          <h1 className="text-4xl font-bold tracking-tight">
            {profile?.flag_emoji && <span aria-hidden>{profile.flag_emoji} </span>}
            {name}
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {profile?.imf_classification && (
            <Chip label={profile.imf_classification} />
          )}
          {profile?.region && <Chip label={profile.region} />}
          {profile?.income_classification && <Chip label={profile.income_classification} />}
        </div>
      </header>

      {/* Indicator tabs. Server-rendered links so switching works without JS. */}
      <nav aria-label="Indicators" className="flex flex-wrap gap-2">
        {available.map((opt) => {
          const active = opt.indicator_code === selected;
          return (
            <Link
              key={opt.indicator_code}
              href={`/country/${iso3}?indicator=${encodeURIComponent(opt.indicator_code)}`}
              aria-current={active ? 'page' : undefined}
              className="rounded-full border px-3 py-1 text-xs transition-colors focus-visible:outline focus-visible:outline-2"
              style={{
                borderColor: active ? 'var(--accent)' : 'var(--border)',
                color: active ? 'var(--accent)' : 'var(--text-secondary)',
                background: active ? 'var(--bg-elevated)' : 'transparent',
                outlineColor: 'var(--accent)',
              }}
            >
              {opt.indicator_name}
            </Link>
          );
        })}
      </nav>

      <div className="grid gap-5 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <PanelHeading>{series?.indicator_name ?? selected}</PanelHeading>
            <SourceChip source={series?.source} />
          </div>
          {series && series.observations.some((o) => o.value !== null) ? (
            /* `key` on the indicator so switching tabs remounts the overlay and the
               in-flight forecast request is aborted rather than racing the new one. */
            <ForecastChart
              key={selected}
              countryCode={iso3}
              indicator={selected}
              observations={series.observations}
              anomalies={flagged}
              unit={series.unit}
              indicatorName={series.indicator_name}
            />
          ) : (
            <EmptyState
              title="No observations for this indicator"
              hint="This country and indicator combination has no data in the database yet. Try another indicator above."
            />
          )}
        </Card>

        {/* Each panel fetches independently, after the chart above has painted. */}
        <div className="flex flex-col gap-5">
          <NarrationPanel key={`n-${selected}`} countryCode={iso3} indicator={selected} />
          <ChartAnalysisPanel key={`v-${selected}`} countryCode={iso3} indicator={selected} />
        </div>
      </div>

      <Card>
        <PanelHeading>Anomalies</PanelHeading>
        {flagged.length > 0 ? (
          <ul className="flex flex-wrap gap-2">
            {flagged.map((a) => (
              <li key={a.date} className="flex items-center gap-2">
                <AnomalyBadge deviationType={a.deviation_type} zScore={a.z_score} />
                <span
                  style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
                  className="text-xs"
                >
                  {a.date.slice(0, 7)} · {formatValue(a.value, series?.unit)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No anomalies flagged for this series" />
        )}
      </Card>

      {flagged.length > 0 && (
        <AnomalyExplanationsPanel key={`a-${selected}`} countryCode={iso3} indicator={selected} />
      )}

      <Card>
        <PanelHeading>Key metrics</PanelHeading>
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {available.slice(0, 8).map((m) => (
            <div key={m.indicator_code}>
              <dt style={{ color: 'var(--text-secondary)' }} className="truncate text-sm">
                {m.indicator_name}
              </dt>
              <dd
                style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}
                className="text-lg font-semibold"
              >
                {formatValue(m.latest_value, m.unit)}
              </dd>
              <p style={{ color: 'var(--text-tertiary)' }} className="text-xs">
                {m.latest_date?.slice(0, 7) ?? '—'}
              </p>
            </div>
          ))}
        </dl>
      </Card>
    </main>
  );
}

function Chip({ label }: { label: string }) {
  return (
    <span
      className="rounded-full border px-2 py-0.5"
      style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)' }}
    >
      {label}
    </span>
  );
}

function NoDataShell({ iso3 }: { iso3: string }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-6 px-6">
      <Link
        href="/"
        className="text-sm underline-offset-2 hover:underline"
        style={{ color: 'var(--accent)' }}
      >
        ← Map
      </Link>
      <Card>
        <EmptyState
          title={`No data for ${iso3} yet`}
          hint="This country has no ingested observations. It may not be covered by the sources currently enabled, or ingestion may not have run for it yet."
        />
      </Card>
    </main>
  );
}
