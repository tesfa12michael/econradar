import Link from 'next/link';
import { Suspense } from 'react';

import { IndicatorSelector } from '@/components/IndicatorSelector';
import { WorldMap } from '@/components/WorldMap';
import { AnomalyBadge, Card, CountryLink, EmptyState, PanelHeading, Skeleton, SourceChip } from '@/components/ui';
import {
  fetchJson,
  formatValue,
  type AnomalyRecord,
  type IndicatorOption,
  type MapData,
} from '@/lib/api';

export const revalidate = 300;

const FALLBACK_INDICATOR = 'NY.GDP.MKTP.KD.ZG';

interface PageProps {
  searchParams: Promise<{ indicator?: string }>;
}

export default async function Home({ searchParams }: PageProps) {
  const { indicator } = await searchParams;

  const options = (await fetchJson<IndicatorOption[]>('/api/v1/indicators')) ?? [];
  // Default to the indicator with the widest country coverage, so the first thing a
  // visitor sees is a full map rather than a sparse one.
  const selected = indicator ?? options[0]?.indicator_code ?? FALLBACK_INDICATOR;

  const [map, anomalies] = await Promise.all([
    fetchJson<MapData>(`/api/v1/map?indicator=${encodeURIComponent(selected)}`),
    fetchJson<AnomalyRecord[]>('/api/v1/anomalies?limit=8'),
  ]);

  const withData = map?.points.filter((p) => p.value !== null) ?? [];
  const sorted = [...withData].sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
  const average =
    withData.length > 0
      ? withData.reduce((sum, p) => sum + (p.value ?? 0), 0) / withData.length
      : null;

  return (
    <main className="flex min-h-screen flex-col">
      <header
        className="flex flex-wrap items-center justify-between gap-4 border-b px-6 py-4"
        style={{ borderColor: 'var(--border)' }}
      >
        <div className="flex items-baseline gap-3">
          <h1 className="text-2xl font-bold tracking-tight">EconRadar</h1>
          <span
            style={{ color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}
            className="text-[10px] uppercase tracking-[0.25em]"
          >
            Live data
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {options.length > 0 && (
            <Suspense fallback={<Skeleton className="h-9 w-72" />}>
              <IndicatorSelector options={options} selected={selected} />
            </Suspense>
          )}
          {/* Topbar navigation only — the map needs the full width (design system). */}
          <Link
            href="/chat"
            className="rounded-lg border px-3 py-2 text-sm transition-colors hover:opacity-80 focus-visible:outline focus-visible:outline-2"
            style={{
              borderColor: 'var(--accent)',
              color: 'var(--accent)',
              outlineColor: 'var(--accent)',
            }}
          >
            Ask the data
          </Link>
        </div>
      </header>

      {map ? (
        <WorldMap
          points={map.points}
          indicatorCode={selected}
          indicatorName={map.indicator_name}
          unit={map.unit}
        />
      ) : (
        <div className="flex h-[60vh] items-center justify-center" style={{ background: 'var(--bg-card)' }}>
          <EmptyState
            title="Map data unavailable"
            hint="The backend did not return data for this indicator. It may not have been ingested yet."
          />
        </div>
      )}

      <div className="grid flex-1 gap-5 p-6 lg:grid-cols-[1fr_1.2fr]">
        <Card>
          <PanelHeading>Recent anomalies</PanelHeading>
          {anomalies && anomalies.length > 0 ? (
            <ul className="flex flex-col gap-3">
              {anomalies.map((a) => (
                <li
                  key={`${a.country_code}-${a.indicator_code}-${a.date}`}
                  className="flex flex-wrap items-center justify-between gap-2 border-b pb-2 last:border-b-0"
                  style={{ borderColor: 'var(--border)' }}
                >
                  <div className="min-w-0">
                    <CountryLink code={a.country_code} name={a.country_name} />
                    <span style={{ color: 'var(--text-tertiary)' }} className="ml-2 text-xs">
                      {a.indicator_name ?? a.indicator_code} · {a.date.slice(0, 7)}
                    </span>
                  </div>
                  <AnomalyBadge deviationType={a.deviation_type} zScore={a.z_score} />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No anomalies flagged yet"
              hint="Anomalies are detected automatically after each scheduled ingestion."
            />
          )}
        </Card>

        <Card>
          <div className="mb-3 flex items-center justify-between gap-3">
            <PanelHeading>{map?.indicator_name ?? 'Global statistics'}</PanelHeading>
            <SourceChip source={map?.source} />
          </div>
          {withData.length > 0 ? (
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="Countries" value={String(withData.length)} />
              <Stat label="World average" value={formatValue(average, map?.unit)} />
              <Stat
                label="Highest"
                value={formatValue(sorted[0]?.value, map?.unit)}
                caption={sorted[0]?.country_name ?? undefined}
              />
              <Stat
                label="Lowest"
                value={formatValue(sorted[sorted.length - 1]?.value, map?.unit)}
                caption={sorted[sorted.length - 1]?.country_name ?? undefined}
              />
            </dl>
          ) : (
            <EmptyState title="No values for this indicator yet" />
          )}
        </Card>
      </div>

      <footer
        className="border-t px-6 py-4 text-xs"
        style={{ borderColor: 'var(--border)', color: 'var(--text-tertiary)' }}
      >
        Data: World Bank · IMF · FRED · BIS · WB DataBank. Forecasting, LLM narration and
        RAG Q&amp;A arrive in Phase 3.
      </footer>
    </main>
  );
}

function Stat({ label, value, caption }: { label: string; value: string; caption?: string }) {
  return (
    <div>
      <dt style={{ color: 'var(--text-secondary)' }} className="text-sm">
        {label}
      </dt>
      <dd
        style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}
        className="text-lg font-semibold"
      >
        {value}
      </dd>
      {caption && (
        <p style={{ color: 'var(--text-tertiary)' }} className="truncate text-xs">
          {caption}
        </p>
      )}
    </div>
  );
}
