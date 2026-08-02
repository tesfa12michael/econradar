'use client';

/** The country profile's centrepiece.
 *
 * Three things are true at once on this chart and the reader has to be able to
 * tell them apart at a glance: what was observed, what was flagged as unusual,
 * and what a model projects. So observation is a solid line, projection is
 * dashed inside a widening band, and the boundary between them is an explicit
 * labelled rule rather than something to be inferred from the line style.
 *
 * The line draws itself on first paint — but only when the document is visible
 * and motion is wanted. Recharts renders an animating line by growing its
 * `strokeDasharray` from zero, so an animation that never runs is a chart with
 * no line in it, and `requestAnimationFrame` does not run in a hidden tab. The
 * resting state is always the finished chart.
 */

import { useReducedMotion } from 'motion/react';
import { useEffect, useState } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { axisTicker, niceDomain } from '@/lib/chartScale';
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
  /** Absent until the async forecast resolves — the chart renders without it. */
  forecast?: ForecastPoint[] | null;
}

interface Row {
  date: string;
  label: string;
  value: number | null;
  median: number | null;
  band: [number, number] | null;
  flagged: boolean;
  zScore: number | null;
  deviation: string | null;
}

export function SeriesChart({
  observations,
  anomalies,
  unit,
  indicatorName,
  forecast,
}: Props) {
  const reduced = useReducedMotion();
  const [draw, setDraw] = useState(false);

  /* False through the server render and the first client render, so the
   * hydrated markup matches and a chart is on screen either way. The draw is
   * switched on afterwards, and only if there is a visible document to draw
   * into. */
  useEffect(() => {
    if (reduced || document.visibilityState !== 'visible') return;
    setDraw(true);
  }, [reduced]);

  const flaggedAt = new Map(anomalies.map((a) => [a.date, a]));

  const history: Row[] = observations
    .filter((o) => o.value !== null)
    .map((o) => {
      const anomaly = flaggedAt.get(o.date);
      return {
        date: o.date,
        label: o.date.slice(0, 7),
        value: o.value as number,
        median: null,
        band: null,
        flagged: Boolean(anomaly),
        zScore: anomaly?.z_score ?? null,
        deviation: anomaly?.deviation_type ?? null,
      };
    });

  const data = [...history];
  let boundary: string | null = null;

  if (forecast && forecast.length > 0 && history.length > 0) {
    // Pin the projection to the last observation so the dashed line continues
    // the solid one instead of starting in mid-air a period later.
    const last = { ...data[data.length - 1] };
    last.median = last.value;
    last.band = [last.value as number, last.value as number];
    data[data.length - 1] = last;
    boundary = last.label;

    for (const point of forecast) {
      data.push({
        date: point.date,
        label: point.date.slice(0, 7),
        value: null,
        median: point.median,
        band: [point.lower, point.upper],
        flagged: false,
        zScore: null,
        deviation: null,
      });
    }
  }

  /* Everything the axis has to contain: observations, the projection's median,
   * and both edges of its band. Leaving the band out clips the p90 tail, which
   * is the half of a forecast a reader most needs to see. */
  const domain = niceDomain(
    data.flatMap((row) => [
      row.value,
      row.median,
      ...(row.band ?? []),
    ]).filter((v): v is number => typeof v === 'number'),
  );

  return (
    <div className="h-[clamp(19rem,42vh,27rem)] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 12, right: 12, bottom: 4, left: 0 }}>
          <defs>
            {/* The band fades as it widens, so the far end of a projection looks
                like the weaker claim it is. */}
            <linearGradient id="forecast-band" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#00D4FF" stopOpacity="0.26" />
              <stop offset="100%" stopColor="#00D4FF" stopOpacity="0.07" />
            </linearGradient>
          </defs>

          <CartesianGrid stroke="var(--hairline)" strokeDasharray="2 5" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: 'var(--ink-dim)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
            stroke="var(--hairline)"
            tickLine={false}
            minTickGap={44}
          />
          <YAxis
            tick={{ fill: 'var(--ink-dim)', fontSize: 11, fontFamily: 'var(--font-mono)' }}
            stroke="var(--hairline)"
            tickLine={false}
            axisLine={false}
            width={56}
            domain={domain ?? ['auto', 'auto']}
            tickCount={6}
            tickFormatter={axisTicker(domain ? domain[1] - domain[0] : 100)}
          />
          <Tooltip
            cursor={{ stroke: 'var(--edge-strong)', strokeWidth: 1 }}
            content={<Readout unit={unit} indicatorName={indicatorName} />}
          />

          {/* Band first, so both lines draw over it. */}
          <Area
            dataKey="band"
            stroke="none"
            fill="url(#forecast-band)"
            isAnimationActive={false}
            connectNulls={false}
          />

          {boundary && (
            <ReferenceLine
              x={boundary}
              stroke="var(--edge-strong)"
              strokeDasharray="3 4"
              label={{
                value: 'forecast',
                position: 'insideTopRight',
                fill: 'var(--ink-dim)',
                fontSize: 11,
                fontFamily: 'var(--font-mono)',
              }}
            />
          )}

          {/* Flagged points are drawn by the line's own dot renderer rather than
              as reference dots: they belong to the series, they inherit its
              draw-in, and they cannot drift out of alignment with it. */}
          <Line
            type="monotone"
            dataKey="value"
            stroke="#00D4FF"
            strokeWidth={1.75}
            dot={renderFlagDot}
            activeDot={{ r: 3.5, fill: '#00D4FF', stroke: '#0A0F1E', strokeWidth: 2 }}
            isAnimationActive={draw}
            animationDuration={900}
            animationEasing="ease-out"
            connectNulls={false}
          />

          {/* Dashed, because a projection is not an observation and the chart
              should say so without needing the legend. */}
          <Line
            type="monotone"
            dataKey="median"
            stroke="#00D4FF"
            strokeWidth={1.75}
            strokeDasharray="5 4"
            dot={false}
            activeDot={{ r: 3.5, fill: '#00D4FF', stroke: '#0A0F1E', strokeWidth: 2 }}
            isAnimationActive={draw}
            animationDuration={700}
            animationBegin={draw ? 700 : 0}
            animationEasing="ease-out"
            connectNulls={false}
          />

        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** A flagged observation: filled core, open ring, halo behind it so it stays
 * legible wherever the line puts it. Amber is the only colour on this chart
 * that is not the accent, and it means exactly one thing.
 *
 * Unflagged points render an empty group rather than nothing — Recharts calls
 * this once per datum and expects an element back from every call.
 */
function renderFlagDot(props: {
  cx?: number;
  cy?: number;
  index?: number;
  payload?: Row;
}) {
  const { cx, cy, payload, index } = props;
  const key = `dot-${payload?.date ?? index}`;
  if (!payload?.flagged || cx === undefined || cy === undefined) {
    return <g key={key} />;
  }
  return (
    <g key={key} pointerEvents="none">
      <circle cx={cx} cy={cy} r={7} fill="#F59E0B" fillOpacity={0.14} />
      <circle cx={cx} cy={cy} r={4.5} fill="none" stroke="#F59E0B" strokeWidth={1.25} />
      <circle cx={cx} cy={cy} r={2} fill="#F59E0B" stroke="#0A0F1E" strokeWidth={1} />
    </g>
  );
}

interface ReadoutProps {
  active?: boolean;
  payload?: { payload: Row }[];
  unit: string | null;
  indicatorName: string | null;
}

/** The same glass surface as the map's country panel, so a reading is a reading
 * wherever you are in the product. Recharts' default tooltip lists every series
 * by its data key, which on this chart means telling the reader about `band`. */
function Readout({ active, payload, unit, indicatorName }: ReadoutProps) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0].payload;
  const projected = row.value === null && row.median !== null;

  return (
    <div
      className="min-w-[11rem] rounded-lg border border-[color:var(--edge)] px-3 py-2.5 backdrop-blur-xl"
      style={{
        background: 'var(--plane-glass)',
        boxShadow: 'inset 0 1px 0 var(--edge-lit), 0 14px 40px -20px rgb(0 0 0 / 0.9)',
      }}
    >
      <p data-numeric className="text-[11px] text-ink-dim">
        {row.label}
      </p>

      {projected ? (
        <>
          <p data-numeric className="mt-1 text-[17px] font-medium text-signal">
            {formatValue(row.median, unit)}
          </p>
          <p data-numeric className="mt-0.5 text-[11px] text-ink-dim">
            projected · p10-p90 {formatValue(row.band?.[0], unit)} to{' '}
            {formatValue(row.band?.[1], unit)}
          </p>
        </>
      ) : (
        <>
          <p data-numeric className="mt-1 text-[17px] font-medium text-ink">
            {formatValue(row.value, unit)}
          </p>
          <p className="mt-0.5 max-w-[16rem] truncate text-[11px] text-ink-dim">
            {indicatorName ?? 'observed'}
          </p>
        </>
      )}

      {row.flagged && (
        <p className="mt-1.5 flex items-center gap-1.5 text-[11px] text-alert">
          <span aria-hidden className="size-1.5 rounded-full bg-alert" />
          Flagged
          {row.zScore !== null && (
            <span data-numeric>
              z {row.zScore > 0 ? '+' : ''}
              {row.zScore.toFixed(1)}
            </span>
          )}
        </p>
      )}
    </div>
  );
}
