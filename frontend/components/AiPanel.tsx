'use client';

/** Async AI panels for the country profile (features 1.5, 2.1, 2.3).
 *
 * These are client components on purpose. The design system bans AI content from
 * blocking page load, so the historical chart is server-rendered and already on
 * screen before any of this mounts; each panel then fetches independently and
 * fills in. A slow narration cannot delay a VLM reading, and neither can delay
 * the chart.
 *
 * Switching indicator aborts the in-flight request rather than racing it — the
 * acceptance criterion in features.md 1.7, and the reason every fetch here is
 * tied to an AbortController keyed on the indicator.
 */

import { useEffect, useState } from 'react';

import {
  fetchAi,
  formatValue,
  modelLabel,
  type AnomalyExplanation,
  type ChartInterpretation,
  type Narration,
} from '@/lib/api';

import { AnomalyBadge, Card, PanelHeading, Skeleton } from './ui';

type State<T> = { status: 'loading' } | { status: 'ready'; data: T } | { status: 'empty' };

/** Fetch on mount, abort on unmount or when `path` changes. */
function useAiResource<T>(path: string | null): State<T> {
  const [state, setState] = useState<State<T>>({ status: 'loading' });

  useEffect(() => {
    if (!path) {
      setState({ status: 'empty' });
      return;
    }
    const controller = new AbortController();
    setState({ status: 'loading' });
    fetchAi<T>(path, controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      setState(data === null ? { status: 'empty' } : { status: 'ready', data });
    });
    return () => controller.abort();
  }, [path]);

  return state;
}

/** Skeleton shaped like the prose it replaces — never a bare spinner. */
function ProseSkeleton() {
  return (
    <div className="space-y-2">
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-11/12" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-4/6" />
    </div>
  );
}

function Unavailable({ reason }: { reason: string }) {
  return (
    <p style={{ color: 'var(--text-tertiary)' }} className="text-sm leading-relaxed">
      {reason}
    </p>
  );
}

/** Attribution for generated text: which model wrote it and how it verified. */
function GenerationChip({
  provider,
  score,
  cached,
}: {
  provider: string;
  score: number | null;
  cached: boolean;
}) {
  const verified = score !== null && score >= 1;
  return (
    <span className="flex flex-wrap items-center gap-1.5 text-xs">
      <span
        className="rounded-full px-2 py-0.5"
        style={{ background: '#3B5998', color: '#F0F4FF' }}
      >
        {modelLabel(provider)}
      </span>
      {score !== null && (
        <span
          className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5"
          style={{
            borderColor: verified ? 'var(--positive)' : 'var(--warn)',
            color: verified ? 'var(--positive)' : 'var(--warn)',
          }}
          title="Every figure in this text was checked against the data it was given."
        >
          <span aria-hidden>{verified ? '✓' : '!'}</span>
          {verified ? 'Figures verified' : `Groundedness ${score.toFixed(2)}`}
        </span>
      )}
      {cached && (
        <span style={{ color: 'var(--text-tertiary)' }} className="whitespace-nowrap">
          cached
        </span>
      )}
    </span>
  );
}

interface SeriesProps {
  countryCode: string;
  indicator: string;
}

export function NarrationPanel({ countryCode, indicator }: SeriesProps) {
  const state = useAiResource<Narration>(
    `narrate/${countryCode}?indicator=${encodeURIComponent(indicator)}`,
  );

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <PanelHeading>AI narration</PanelHeading>
        {state.status === 'ready' && (
          <GenerationChip
            provider={state.data.provider}
            score={state.data.groundedness_score}
            cached={state.data.cached}
          />
        )}
      </div>
      <div aria-live="polite" aria-busy={state.status === 'loading'}>
        {state.status === 'loading' && <ProseSkeleton />}
        {state.status === 'empty' && (
          <Unavailable reason="Narration is not available for this series right now. It is written only from the numbers on this page — when no provider returns a verifiable reading, nothing is shown rather than something unchecked." />
        )}
        {state.status === 'ready' && (
          <p
            style={{ color: 'var(--text-secondary)' }}
            className="text-base leading-relaxed whitespace-pre-line"
          >
            {state.data.text}
          </p>
        )}
      </div>
    </Card>
  );
}

export function ChartAnalysisPanel({ countryCode, indicator }: SeriesProps) {
  const state = useAiResource<ChartInterpretation>(
    `vlm-interpret/${countryCode}?indicator=${encodeURIComponent(indicator)}`,
  );

  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <PanelHeading>AI chart analysis</PanelHeading>
        {state.status === 'ready' && (
          <GenerationChip
            provider={state.data.provider}
            score={state.data.groundedness_score}
            cached={state.data.cached}
          />
        )}
      </div>
      <div aria-live="polite" aria-busy={state.status === 'loading'}>
        {state.status === 'loading' && <ProseSkeleton />}
        {state.status === 'empty' && (
          <Unavailable reason="No chart reading is available for this series right now. A vision model is shown the rendered chart and asked to describe it; readings that cite figures absent from the data are discarded." />
        )}
        {state.status === 'ready' && (
          <p
            style={{ color: 'var(--text-secondary)' }}
            className="text-base leading-relaxed whitespace-pre-line"
          >
            {state.data.text}
          </p>
        )}
      </div>
    </Card>
  );
}

export function AnomalyExplanationsPanel({ countryCode, indicator }: SeriesProps) {
  const state = useAiResource<AnomalyExplanation[]>(
    `anomaly-explanations/${countryCode}?indicator=${encodeURIComponent(indicator)}&limit=3`,
  );

  if (state.status === 'ready' && state.data.length === 0) return null;

  return (
    <Card>
      <PanelHeading>What the flagged points look like</PanelHeading>
      <div aria-live="polite" aria-busy={state.status === 'loading'} className="space-y-4">
        {state.status === 'loading' && (
          <>
            <Skeleton className="h-3 w-1/3" />
            <ProseSkeleton />
          </>
        )}
        {state.status === 'empty' && (
          <Unavailable reason="Explanations are not available right now." />
        )}
        {state.status === 'ready' &&
          state.data.map((item) => (
            <div key={item.date} className="border-t pt-3 first:border-t-0 first:pt-0"
                 style={{ borderColor: 'var(--border)' }}>
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <AnomalyBadge deviationType={item.deviation_type} zScore={item.z_score} />
                <span
                  className="text-xs"
                  style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
                >
                  {item.date.slice(0, 7)} · {formatValue(item.value)}
                </span>
              </div>
              <p style={{ color: 'var(--text-secondary)' }} className="text-sm leading-relaxed">
                {item.explanation ?? 'No verified explanation is available for this point.'}
              </p>
            </div>
          ))}
      </div>
    </Card>
  );
}
