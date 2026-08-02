'use client';

/** The historical chart, its summary figures, and an async forecast overlay
 * (features 1.4 and 1.7).
 *
 * The chart renders from server-supplied history on first paint. The forecast is
 * fetched afterwards and merged in — a cold GPU at the far end of the cascade
 * can take twenty seconds, and the design system is explicit that AI content
 * must never hold up the chart. Switching series aborts the pending request
 * instead of racing it.
 *
 * The summary row underneath is computed from the plotted observations, so
 * every figure on it is one the reader can find on the line above it.
 */

import { useEffect, useState } from 'react';

import { Meta } from '@/components/primitives';
import {
  fetchAi,
  formatValue,
  modelLabel,
  type AnomalyRecord,
  type Forecast,
  type Observation,
} from '@/lib/api';
import type { SeriesStats } from '@/lib/series';

import { SeriesChart } from './SeriesChart';

interface Props {
  countryCode: string;
  indicator: string;
  observations: Observation[];
  anomalies: AnomalyRecord[];
  unit: string | null;
  indicatorName: string | null;
  stats: SeriesStats;
}

export function ForecastChart({
  countryCode,
  indicator,
  observations,
  anomalies,
  unit,
  indicatorName,
  stats,
}: Props) {
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [pending, setPending] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setForecast(null);
    setPending(true);
    fetchAi<Forecast>(
      `forecast/${countryCode}?indicator=${encodeURIComponent(indicator)}`,
      controller.signal,
    ).then((data) => {
      if (controller.signal.aborted) return;
      setForecast(data);
      setPending(false);
    });
    return () => controller.abort();
  }, [countryCode, indicator]);

  return (
    <>
      <SeriesChart
        observations={observations}
        anomalies={anomalies}
        unit={unit}
        indicatorName={indicatorName}
        forecast={forecast?.points ?? null}
      />

      {/* Not four cards. These are four readings off the line above, so they are
          set as one row of figures divided by rules — the same way the axis
          labels are, because that is what they are. */}
      <dl className="mt-5 flex flex-wrap items-stretch gap-y-4 border-t border-[color:var(--hairline)] pt-4">
        <Reading label="Latest" value={formatValue(stats.latest?.value, unit)} at={stats.latest?.date} />
        <Reading label="Lowest" value={formatValue(stats.min?.value, unit)} at={stats.min?.date} />
        <Reading label="Highest" value={formatValue(stats.max?.value, unit)} at={stats.max?.date} />
        <Reading
          label="Observations"
          value={String(stats.count)}
          at={undefined}
          note={
            stats.firstDate
              ? `${stats.firstDate.slice(0, 4)}-${stats.lastDate?.slice(0, 4)}`
              : undefined
          }
          last
        />
      </dl>

      <p className="mt-3.5 max-w-[70ch]" aria-live="polite">
        <Meta className="leading-relaxed">
          {pending && 'Loading the forecast…'}
          {!pending && forecast && (
            <>
              The dashed line and the band beyond {forecast.points[0]?.date.slice(0, 4)} are a{' '}
              {forecast.horizon}-period projection from {modelLabel(forecast.model_used)}: the
              median, inside a p10-p90 interval that widens with the horizon. A projection is not
              an observation.
            </>
          )}
          {!pending &&
            !forecast &&
            'No forecast is available for this series. It may be too short to model — a series below the minimum is refused rather than projected from noise — or every model in the cascade may be unreachable.'}
        </Meta>
      </p>
    </>
  );
}

function Reading({
  label,
  value,
  at,
  note,
  last,
}: {
  label: string;
  value: string;
  at?: string;
  note?: string;
  last?: boolean;
}) {
  return (
    <div
      className={[
        'min-w-[7.5rem] flex-1 pr-6',
        // --edge rather than --hairline: at one pixel on this surface the
        // hairline is invisible, which reads as four columns that happen to sit
        // near each other rather than as one divided row.
        last ? '' : 'mr-6 border-r border-[color:var(--edge)]',
      ].join(' ')}
    >
      <dt>
        <Meta className="uppercase tracking-[0.14em]">{label}</Meta>
      </dt>
      <dd data-numeric className="mt-1 text-[19px] font-medium tracking-[-0.01em] text-ink">
        {value}
      </dd>
      {(at || note) && (
        <dd className="mt-0.5">
          <Meta>{note ?? at?.slice(0, 4)}</Meta>
        </dd>
      )}
    </div>
  );
}
