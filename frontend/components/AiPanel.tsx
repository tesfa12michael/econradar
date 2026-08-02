'use client';

/** The generated panels on a country profile (features 2.1 and 2.3).
 *
 * Client components on purpose. The chart is server-rendered and painted before
 * any of this mounts; each panel then fetches on its own, so a slow chart
 * reading cannot delay the flagged-point explanations and neither can hold up
 * the chart. Switching indicator aborts the request in flight rather than
 * racing it — the acceptance criterion in features.md 1.7, and why every fetch
 * here is tied to an `AbortController` keyed on the indicator.
 *
 * The presentation is deliberate. Generated prose sits on its own surface, set
 * wider and one step lighter than the marginalia around it, under a header that
 * says which model wrote it and that every figure in it was checked against the
 * records it was given. That verdict is the most important thing on the panel:
 * the text is only worth reading because something rejected the version that
 * was wrong.
 */

import { CheckCircle, Warning } from '@phosphor-icons/react/dist/ssr';
import { useEffect, useState } from 'react';

import {
  AnomalyBadge,
  Empty,
  Meta,
  ProseShimmer,
  SectionHead,
  Shimmer,
} from '@/components/primitives';
import {
  fetchAi,
  formatValue,
  modelLabel,
  type AnomalyExplanation,
  type ChartInterpretation,
} from '@/lib/api';

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

/** Who wrote it, and whether its figures survived the check.
 *
 * Not a coloured pill. A verdict rendered as a badge reads as a decoration
 * beside the text; rendered as a line of mono under the heading it reads as
 * what it is — a record of a check that was run, which could have failed. */
function Provenance({
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
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span
        className="inline-flex items-center gap-1.5"
        title="Every figure in this text was checked against the records the model was shown. Text that cites a figure absent from them is discarded rather than published."
      >
        {score !== null &&
          (verified ? (
            <CheckCircle aria-hidden weight="fill" className="size-3.5 text-positive" />
          ) : (
            <Warning aria-hidden weight="fill" className="size-3.5 text-alert" />
          ))}
        <Meta className={verified ? 'text-positive' : 'text-alert'}>
          {score === null
            ? 'unverified'
            : verified
              ? 'figures checked'
              : `groundedness ${score.toFixed(2)}`}
        </Meta>
      </span>
      <Meta>{modelLabel(provider)}</Meta>
      {cached && <Meta>cached</Meta>}
    </span>
  );
}

interface SeriesProps {
  countryCode: string;
  indicator: string;
}

export function ChartAnalysisPanel({ countryCode, indicator }: SeriesProps) {
  const state = useAiResource<ChartInterpretation>(
    `vlm-interpret/${countryCode}?indicator=${encodeURIComponent(indicator)}`,
  );

  return (
    <section
      aria-labelledby="reading-heading"
      className="rounded-lg border border-[color:var(--hairline)] bg-[color:var(--plane-2)] p-5 shadow-[inset_0_1px_0_var(--edge-lit)]"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="reading-heading" className="text-[15px] font-medium tracking-tight text-ink">
          What the chart shows
        </h2>
        {state.status === 'ready' && (
          <Provenance
            provider={state.data.provider}
            score={state.data.groundedness_score}
            cached={state.data.cached}
          />
        )}
        {state.status === 'loading' && <Shimmer className="h-3 w-40" />}
      </div>

      <p className="mt-1">
        <Meta>
          a vision model is shown the rendered chart and describes it; the figures come
          from the data behind it, not from the picture
        </Meta>
      </p>

      <div aria-live="polite" aria-busy={state.status === 'loading'} className="mt-4">
        {state.status === 'loading' && <ProseShimmer lines={5} />}

        {state.status === 'empty' && (
          <Empty
            className="py-2"
            title="No reading is available for this series"
            hint="A reading is generated the first time someone opens a series and kept until its data changes. This one is either still being written or was withheld because its figures did not check out."
          />
        )}

        {state.status === 'ready' && (
          <p className="max-w-[64ch] whitespace-pre-line text-[15px] leading-[1.72] text-ink-muted">
            {state.data.text}
          </p>
        )}
      </div>
    </section>
  );
}

export function AnomalyExplanationsPanel({ countryCode, indicator }: SeriesProps) {
  const state = useAiResource<AnomalyExplanation[]>(
    `anomaly-explanations/${countryCode}?indicator=${encodeURIComponent(indicator)}&limit=3`,
  );

  if (state.status === 'ready' && state.data.length === 0) return null;

  return (
    <section aria-labelledby="flagged-detail-heading">
      <SectionHead
        title={<span id="flagged-detail-heading">The flagged points, in detail</span>}
        meta={<Meta>most severe first · the explanation never names a cause</Meta>}
      />

      <div aria-live="polite" aria-busy={state.status === 'loading'} className="mt-4 space-y-5">
        {state.status === 'loading' && (
          <>
            <Shimmer className="h-3 w-48" />
            <ProseShimmer lines={3} />
          </>
        )}

        {state.status === 'empty' && (
          <Empty
            className="py-2"
            title="No explanations are available"
            hint="Explanations are written when a flagged point is first opened and kept afterwards. Nothing is shown here rather than a guess at what happened."
          />
        )}

        {state.status === 'ready' &&
          state.data.map((item) => (
            <article
              key={item.date}
              className="border-t border-[color:var(--hairline)] pt-4 first:border-t-0 first:pt-0"
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <AnomalyBadge deviationType={item.deviation_type} zScore={item.z_score} />
                <Meta className="text-ink-muted">
                  {item.date.slice(0, 7)} · {formatValue(item.value)}
                </Meta>
              </div>
              <p className="mt-2 max-w-[64ch] text-[14px] leading-[1.7] text-ink-muted">
                {item.explanation ?? 'No verified explanation is available for this point.'}
              </p>
            </article>
          ))}
      </div>
    </section>
  );
}
