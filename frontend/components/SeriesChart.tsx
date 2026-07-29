'use client';

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { formatValue, type AnomalyRecord, type Observation } from '@/lib/api';

interface Props {
  observations: Observation[];
  anomalies: AnomalyRecord[];
  unit: string | null;
  indicatorName: string | null;
}

export function SeriesChart({ observations, anomalies, unit, indicatorName }: Props) {
  const data = observations
    .filter((o) => o.value !== null)
    .map((o) => ({ date: o.date, label: o.date.slice(0, 7), value: o.value as number }));

  const flagged = new Map(anomalies.map((a) => [a.date, a]));
  const points = data.filter((d) => flagged.has(d.date));

  return (
    <div className="h-[22rem] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
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
            formatter={(value) => [
              formatValue(typeof value === 'number' ? value : null, unit),
              indicatorName ?? 'Value',
            ]}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#00D4FF"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#00D4FF' }}
            isAnimationActive={false}
          />
          {points.map((p) => (
            <ReferenceDot
              key={p.date}
              x={p.label}
              y={p.value}
              r={5}
              fill="#F59E0B"
              stroke="#0A0F1E"
              strokeWidth={1.5}
              // Anomalies are also listed as text badges below the chart, so colour is
              // never the only way this information is conveyed.
              aria-label={`Anomaly at ${p.label}`}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
