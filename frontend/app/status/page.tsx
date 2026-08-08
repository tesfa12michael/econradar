import { Freshness } from '@/components/status/Freshness';
import { SiteFooter } from '@/components/home/SiteFooter';
import { TopBar } from '@/components/home/TopBar';
import { Figure, Hairline, Meta, SectionHead } from '@/components/primitives';
import { Reveal } from '@/components/motion/Reveal';
import { fetchJson, type SystemStatus } from '@/lib/api';
import { placeSources } from '@/lib/freshness';

/** Shorter than the rest of the site. Freshness is this page's entire subject, so
 * a five-minute cache would mean the page reporting staleness is itself stale by
 * more than the interval it is reporting in. */
export const revalidate = 60;

export const metadata = {
  title: 'System status · EconRadar',
  description:
    'What EconRadar holds, when each source was last pulled, and what the chat endpoint has done.',
};

export default async function Status() {
  const status = await fetchJson<SystemStatus>('/status', 60);
  const now = Date.now();

  return (
    <>
      <TopBar status={status?.status ?? null} current="status" />

      <main id="main" className="mx-auto max-w-5xl px-5 pb-4 pt-10 sm:px-6">
        <header>
          <h1 className="text-[clamp(1.6rem,3vw,2.15rem)] font-medium leading-[1.1] tracking-[-0.025em] text-ink">
            System status
          </h1>
          {/* Not "read at <render time>". This page is served from a cache, so the
              payload below can be up to a minute older than the moment it is
              rendered — and on the first request after a deploy it can be the
              build's copy, which is older still. Stamping it with render time
              would be the page telling its own small lie about freshness. */}
          <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <Verdict status={status?.status ?? null} />
            {status?.environment && <Meta>{status.environment}</Meta>}
            <Meta>re-read at most once a minute</Meta>
          </p>
        </header>

        {status ? (
          <>
            <Section title="Records held" meta="counted by the database, not maintained by hand">
              <Holdings status={status} />
            </Section>

            {/* Counted rather than written as "five". The number of connectors is
                a fact the payload carries; hardcoding it means the one time it
                changes, the page is confidently wrong about its own picture. */}
            <Section
              title="Last pulled"
              meta={`${(status.sources ?? []).length} connectors on one axis, oldest run at the left`}
            >
              <Freshness data={placeSources(status.sources ?? [], now)} />
            </Section>

            <Section title="The chat endpoint" meta={chatWindow(status)}>
              <Chat status={status} />
            </Section>
          </>
        ) : (
          <Unreachable />
        )}
      </main>

      <SiteFooter sources={status?.sources ?? []} />
    </>
  );
}

function Section({
  title,
  meta,
  children,
}: {
  title: string;
  meta: string;
  children: React.ReactNode;
}) {
  return (
    <Reveal className="mt-12 border-t border-[color:var(--hairline)] pt-7">
      <SectionHead title={title} meta={<Meta>{meta}</Meta>} />
      <div className="mt-5">{children}</div>
    </Reveal>
  );
}

/** The one thing a reader came here for, in the backend's own word.
 *
 * `operational` and `degraded` are the two values the endpoint emits; anything else
 * is passed through rather than mapped, because inventing a label for a state the
 * backend invented would hide exactly the case worth seeing. */
function Verdict({ status }: { status: string | null }) {
  const operational = status === 'operational';
  const colour = status === null ? 'var(--negative)' : operational ? 'var(--positive)' : 'var(--alert)';
  const word = status === null ? 'unreachable' : status;

  return (
    <span className="inline-flex items-center gap-2">
      <span
        aria-hidden
        className="size-2 rounded-full"
        style={{ background: colour, boxShadow: `0 0 9px ${colour}` }}
      />
      <span className="text-[15px] font-medium capitalize" style={{ color: colour }}>
        {word}
      </span>
    </span>
  );
}

/** Four counts, divided rather than boxed.
 *
 * A row of bordered tiles is the reflex here and it would be the wrong shape: these
 * are four readings of one store, not four separate things, and hairlines say that
 * where four cards would say the opposite. */
function Holdings({ status }: { status: SystemStatus }) {
  const items = [
    { label: 'observations', value: status.observations_tracked },
    { label: 'countries', value: status.countries_tracked },
    { label: 'series', value: status.indicators_tracked },
    { label: 'flagged', value: status.anomalies_flagged },
  ];

  return (
    <dl className="grid grid-cols-2 gap-px overflow-hidden sm:grid-cols-4">
      {items.map((item, index) => (
        <div
          key={item.label}
          className={
            'py-1 sm:py-0' +
            (index > 0 ? ' sm:border-l sm:border-[color:var(--hairline)] sm:pl-6' : '')
          }
        >
          <dd>
            <Figure size="lg">{(item.value ?? 0).toLocaleString('en-US')}</Figure>
          </dd>
          <dt className="mt-1">
            <Meta>{item.label}</Meta>
          </dt>
        </div>
      ))}
    </dl>
  );
}

/** The window the chat counters describe.
 *
 * `services/telemetry.py` keeps them in one process and says so outright: they reset
 * on restart. A status page that implied they were all-time would be reporting a
 * quiet system as a well-behaved one. */
function chatWindow(status: SystemStatus): string {
  if (!status.chat) return 'the endpoint reported no counters';
  return 'counted in memory, so these reset when the backend restarts';
}

function Chat({ status }: { status: SystemStatus }) {
  const chat = status.chat;

  const verification = (
    <div>
      <p className="flex items-baseline gap-3">
        <span className="text-[13px] text-ink">Groundedness verification</span>
        <Meta
          className={status.groundedness_verification === 'active' ? 'text-positive' : 'text-alert'}
        >
          {status.groundedness_verification ?? 'unknown'}
        </Meta>
      </p>
      <p className="mt-1.5 max-w-[62ch] text-[13px] leading-relaxed text-ink-dim">
        Every figure in a generated answer is checked against the rows the query
        returned. An answer quoting a number that is not in them is withdrawn rather
        than shown.
      </p>
    </div>
  );

  if (!chat) {
    return <div className="space-y-5">{verification}</div>;
  }

  return (
    <div className="space-y-6">
      {verification}
      <Hairline />

      <div className="grid gap-x-10 gap-y-6 sm:grid-cols-2">
        <div>
          <Meta className="uppercase tracking-[0.14em]">Today</Meta>
          <p className="mt-2 flex items-baseline gap-2">
            <Figure size="lg">{chat.chat_requests_today.toLocaleString('en-US')}</Figure>
            <Meta>of {chat.daily_budget.toLocaleString('en-US')} admitted</Meta>
          </p>
          {/* "Admitted", not "answered". The limiter runs as a route dependency,
              ahead of body validation, so a request that is let through and then
              rejected as malformed still counted. Calling these answers would
              overstate what the quota bought. */}
          <Meta className="mt-2 block max-w-[46ch]">
            A whole-deployment ceiling, counted where the limiter runs: before the
            body is validated. Malformed requests spend it too, so this is traffic
            admitted rather than questions answered.
          </Meta>
        </div>

        <div>
          <Meta className="uppercase tracking-[0.14em]">Since the last restart</Meta>
          {chat.requests > 0 ? (
            <dl className="mt-2 space-y-1.5">
              <Row label="questions answered" value={chat.requests.toLocaleString('en-US')} />
              <Row label="database queries" value={chat.tool_calls.toLocaleString('en-US')} />
              {chat.tool_failures > 0 && (
                <Row
                  label="queries that missed"
                  value={chat.tool_failures.toLocaleString('en-US')}
                />
              )}
              {chat.mean_seconds !== null && (
                <Row label="mean wait" value={`${chat.mean_seconds.toFixed(1)}s`} />
              )}
              {chat.cache_hit_rate !== null && (
                <Row label="served from cache" value={percent(chat.cache_hit_rate)} />
              )}
              {chat.refusal_rate !== null && (
                <Row label="declined as out of scope" value={percent(chat.refusal_rate)} />
              )}
              {chat.fallback_rate !== null && (
                <Row label="needed a fallback provider" value={percent(chat.fallback_rate)} />
              )}
            </dl>
          ) : (
            <Meta className="mt-2 block max-w-[46ch]">
              No questions since the backend last started. These counters live in the
              process, so a restart is the only thing that clears them.
            </Meta>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-[color:var(--hairline)] pb-1.5 last:border-b-0">
      <dt>
        <Meta className="text-ink-muted">{label}</Meta>
      </dt>
      <dd>
        <Figure size="sm">{value}</Figure>
      </dd>
    </div>
  );
}

function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

/** The status page's own failure, which is itself a status.
 *
 * This is the one page where "could not load" is not a shrug: the reader asked
 * whether the backend is up and the answer, demonstrated rather than asserted, is
 * that it could not be reached from here. Saying which of the two is at fault would
 * be a guess, so it says what it knows and what it does not. */
function Unreachable() {
  return (
    <div className="mt-12 border-t border-[color:var(--hairline)] pt-7">
      <SectionHead
        title="No answer from the backend"
        meta={<Meta>which is, on this page, the finding rather than an error</Meta>}
      />
      <p className="mt-4 max-w-[62ch] text-[14px] leading-[1.75] text-ink-muted">
        This page asks the API for its own status and renders whatever comes back. The
        request did not return, so the figures below the fold are absent rather than
        stale, and nothing here has been filled in from a previous read.
      </p>
      <p className="mt-3 max-w-[62ch] text-[14px] leading-[1.75] text-ink-muted">
        Whether the API is down or unreachable only from this renderer, this page
        cannot tell you, and guessing between the two would be the wrong kind of
        confidence for a status page. The map and the country profiles will be showing
        their own empty states for the same reason.
      </p>
    </div>
  );
}
