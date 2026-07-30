'use client';

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import {
  formatValue,
  type AnomalyRecord,
  type ForecastPoint,
  type Observation,
} from '@/lib/api';

interface Props {
  observations: Observation[];
  anomalies: AnomalyRecord[];
  unit: string | null;
  indicatorName: string | null;
  /** Absent until the async forecast panel resolves — the chart renders without it. */
  forecast?: ForecastPoint[] | null;
}

interface Row {
  date: string;
  label: string;
  value: number | null;
  median: number | null;
  band: [number, number] | null;
}

export function SeriesChart({
  observations,
  anomalies,
  unit,
  indicatorName,
  forecast,
}: Props) {
  const history: Row[] = observations
    .filter((o) => o.value !== null)
    .map((o) => ({
      date: o.date,
      label: o.date.slice(0, 7),
      value: o.value as number,
      median: null,
      band: null,
    }));

  const data = [...history];
  if (forecast && forecast.length > 0 && history.length > 0) {
    // Pin the projection to the last observation so the dashed line continues the
    // solid one instead of starting in mid-air a period later.
    const last = data[data.length - 1];
    last.median = last.value;
    last.band = [last.value as number, last.value as number];
    for (const point of forecast) {
      data.push({
        date: point.date,
        label: point.date.slice(0, 7),
        value: null,
        median: point.median,
        band: [point.lower, point.upper],
      });
    }
  }

  const flagged = new Set(anomalies.map((a) => a.date));
  const points = history.filter((d) => flagged.has(d.date));

  return (
    <div className="h-[22rem] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid stroke="#1F2D45" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: '#8B9EC7', fontSize: 11, fontFamily: 'var(--font-mono)' }}
            stroke="#1F2D45"
            minTickGap={28}
          />
          <YAxis
            tick={{ fill: '#8B9EC7', fontSize: 11, fontFamily: 'var(--font-mono)' }}
            stroke="#1F2D45"
            width={64}
          />
          <Tooltip
            contentStyle={{
              background: '#1A2235',
              border: '1px solid #1F2D45',
              borderRadius: 8,
              color: '#F0F4FF',
            }}
            labelStyle={{ color: '#8B9EC7' }}
            formatter={(value, name) => {
              if (name === 'band' && Array.isArray(value)) {
                return [
                  `${formatValue(value[0], unit)} – ${formatValue(value[1], unit)}`,
                  'Forecast p10–p90',
                ];
              }
              const numeric = typeof value === 'number' ? value : null;
              if (name === 'median') return [formatValue(numeric, unit), 'Forecast (median)'];
              return [formatValue(numeric, unit), indicatorName ?? 'Value'];
            }}
          />
          {/* Confidence band first, so the lines draw over it. */}
          <Area
            dataKey="band"
            stroke="none"
            fill="#00D4FF"
            fillOpacity={0.18}
            isAnimationActive={false}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#00D4FF"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#00D4FF' }}
            isAnimationActive={false}
            connectNulls={false}
          />
          {/* Dashed, because a projection is not an observation and the chart should
              say so without needing the legend. */}
          <Line
            type="monotone"
            dataKey="median"
            stroke="#00D4FF"
            strokeWidth={2}
            strokeDasharray="6 4"
            dot={false}
            activeDot={{ r: 4, fill: '#00D4FF' }}
            isAnimationActive={false}
            connectNulls={false}
          />
          {points.map((p) => (
            <ReferenceDot
              key={p.date}
              x={p.label}
              y={p.value as number}
              r={5}
              fill="#F59E0B"
              stroke="#0A0F1E"
              strokeWidth={1.5}
              // Anomalies are also listed as text badges below the chart, so colour is
              // never the only way this information is conveyed.
              aria-label={`Anomaly at ${p.label}`}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
