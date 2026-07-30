'use client';

/** The historical chart plus an async forecast overlay (features 1.4 and 1.7).
 *
 * The chart renders from server-supplied history on first paint. The forecast is
 * fetched afterwards and merged in — a cold GPU on the far end of the cascade can
 * take twenty seconds, and the design system is explicit that AI content must
 * never hold up the chart. Switching indicator aborts the pending request instead
 * of racing it.
 */

import { useEffect, useState } from 'react';

import {
  fetchAi,
  modelLabel,
  type AnomalyRecord,
  type Forecast,
  type Observation,
} from '@/lib/api';

import { SeriesChart } from './SeriesChart';

interface Props {
  countryCode: string;
  indicator: string;
  observations: Observation[];
  anomalies: AnomalyRecord[];
  unit: string | null;
  indicatorName: string | null;
}

export function ForecastChart({
  countryCode,
  indicator,
  observations,
  anomalies,
  unit,
  indicatorName,
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
      <p
        className="mt-2 text-xs"
        style={{ color: 'var(--text-tertiary)' }}
        aria-live="polite"
      >
        {pending && 'Loading forecast…'}
        {!pending && forecast && (
          <>
            Dashed line and shaded band: {forecast.horizon}-period forecast from{' '}
            <span style={{ color: 'var(--text-secondary)' }}>
              {modelLabel(forecast.model_used)}
            </span>
            , median with a p10–p90 interval.
          </>
        )}
        {!pending && !forecast &&
          'No forecast is available for this series — it may be too short to model, or every model in the cascade may be unreachable.'}
      </p>
    </>
  );
}
