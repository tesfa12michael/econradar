'use client';

/** What the page looks like before anything has been asked.
 *
 * A blank field with a placeholder would waste the most useful moment on the
 * page. What a reader needs here is not encouragement, it is *calibration* —
 * knowing what this thing can and cannot answer before they spend a question
 * finding out. So the opening states the architecture plainly: there are
 * exactly two ways it can look something up, and neither of them is the web.
 *
 * That count is the design, not an implementation detail. With no search tool
 * and no general-knowledge tool, a figure the database does not hold has no
 * path into an answer — the model is not asked to resist the temptation, it is
 * not given one. Saying so up front is both the honest framing and the most
 * interesting thing about the system.
 *
 * Everything on it is live: the holdings come from `/status`, and the flagged
 * readings are real detections that turn into real questions when clicked.
 */

import { Database, Ranking } from '@phosphor-icons/react/dist/ssr';

import { AnomalyBadge, Meta } from '@/components/primitives';
import { RevealGroup, RevealItem } from '@/components/motion/Reveal';
import { formatValue, indicatorTitle, type AnomalyRecord, type SystemStatus } from '@/lib/api';

const SUGGESTIONS = [
  'Which country has the highest government debt as a share of GDP?',
  'How does inflation in Nigeria compare with Ghana?',
  'What happened to Brazilian policy rates in the 1990s?',
  'What is the GDP growth of the British Virgin Islands?',
];

export function Opening({
  status,
  flagged,
  onAsk,
}: {
  status: SystemStatus | null;
  flagged: AnomalyRecord[];
  onAsk: (question: string) => void;
}) {
  const count = (n: number | undefined) => (n ?? 0).toLocaleString('en-US');

  return (
    <div>
      <h1 className="text-[clamp(1.75rem,3.6vw,2.5rem)] font-medium leading-[1.1] tracking-[-0.03em]">
        Ask the data
      </h1>
      {status && (
        <p className="mt-3">
          <Meta className="text-ink-muted">
            {count(status.observations_tracked)} observations · {count(status.countries_tracked)}{' '}
            countries · {count(status.indicators_tracked)} series
          </Meta>
        </p>
      )}

      <div className="mt-8 border-t border-[color:var(--hairline)] pt-5">
        <p className="max-w-[58ch] text-[14px] leading-[1.7] text-ink-muted">
          There are exactly two ways this can look something up.
        </p>

        <dl className="mt-4 space-y-3">
          <Capability
            Glyph={Database}
            name="query_observations"
            what="one country, one series, any window of years"
          />
          <Capability
            Glyph={Ranking}
            name="rank_countries"
            what="every country at once, which is what a superlative actually requires"
          />
        </dl>

        <p className="mt-4 max-w-[58ch] text-[14px] leading-[1.7] text-ink-muted">
          There is no web search and no general-knowledge tool, so a figure this database
          does not hold has no path into an answer. Ask it about something outside the data
          and it will tell you that, rather than guess.
        </p>
      </div>

      <div className="mt-9 grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)]">
        <section aria-labelledby="start-heading">
          <h2 id="start-heading" className="text-[13px] font-medium text-ink">
            Start with
          </h2>
          <RevealGroup className="mt-3 space-y-px" step={0.04}>
            {SUGGESTIONS.map((question) => (
              <RevealItem key={question}>
                <button
                  type="button"
                  onClick={() => onAsk(question)}
                  className="group flex w-full items-start gap-2.5 rounded-md border border-transparent px-3 py-2.5 text-left transition-colors duration-200 hover:border-[color:var(--hairline)] hover:bg-[color:var(--plane-2)]"
                >
                  <span
                    aria-hidden
                    className="mt-[3px] text-[12px] text-ink-dim transition-colors duration-200 group-hover:text-signal"
                  >
                    ›
                  </span>
                  <span className="text-[14px] leading-snug text-ink-muted transition-colors duration-200 group-hover:text-ink">
                    {question}
                  </span>
                </button>
              </RevealItem>
            ))}
          </RevealGroup>
        </section>

        {flagged.length > 0 && (
          <section aria-labelledby="flagged-start-heading">
            <h2 id="flagged-start-heading" className="text-[13px] font-medium text-ink">
              Or something flagged this week
            </h2>
            <p className="mt-1">
              <Meta>real detections, most severe first</Meta>
            </p>
            <RevealGroup className="mt-3 space-y-px" step={0.04}>
              {flagged.map((anomaly) => (
                <RevealItem key={`${anomaly.country_code}-${anomaly.indicator_code}-${anomaly.date}`}>
                  <button
                    type="button"
                    onClick={() => onAsk(questionFor(anomaly))}
                    className="group flex w-full flex-col gap-1.5 rounded-md border border-transparent px-3 py-2.5 text-left transition-colors duration-200 hover:border-[color:var(--hairline)] hover:bg-[color:var(--plane-2)]"
                  >
                    <span className="flex items-center justify-between gap-3">
                      <span className="truncate text-[14px] text-ink-muted transition-colors duration-200 group-hover:text-ink">
                        {anomaly.country_name ?? anomaly.country_code}
                      </span>
                      <span data-numeric className="shrink-0 text-[13px] text-ink">
                        {formatValue(anomaly.value)}
                      </span>
                    </span>
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <AnomalyBadge
                        deviationType={anomaly.deviation_type}
                        zScore={anomaly.z_score}
                      />
                      <Meta className="truncate">
                        {indicatorTitle(anomaly.indicator_name) || anomaly.indicator_code}
                      </Meta>
                    </span>
                  </button>
                </RevealItem>
              ))}
            </RevealGroup>
          </section>
        )}
      </div>
    </div>
  );
}

function Capability({
  Glyph,
  name,
  what,
}: {
  Glyph: typeof Database;
  name: string;
  what: string;
}) {
  return (
    <div className="flex items-baseline gap-3">
      <Glyph aria-hidden weight="duotone" className="size-4 shrink-0 translate-y-[3px] text-signal-dim" />
      <dt data-numeric className="shrink-0 text-[13px] text-ink">
        {name}
      </dt>
      <dd className="text-[13px] leading-relaxed text-ink-dim">{what}</dd>
    </div>
  );
}

/** Turn a detection into a question the agent can actually answer.
 *
 * Named after what was flagged and when, so the query it triggers reads the
 * same series the badge came from rather than something adjacent. */
function questionFor(anomaly: AnomalyRecord): string {
  const country = anomaly.country_name ?? anomaly.country_code;
  const series = indicatorTitle(anomaly.indicator_name) || anomaly.indicator_code;
  return `What happened to ${country}'s ${series.toLowerCase()} around ${anomaly.date.slice(0, 7)}?`;
}
