'use client';

/** One question and what came back from it.
 *
 * The order the events arrive in is the design. A tool-calling turn is not a
 * token stream (decision #38), so there is no typewriter to watch — what there
 * is instead is the agent going to the database, and that is more interesting
 * than characters appearing. The queries land first, then the sources they
 * produced, then the answer, then the verdict on it. A reader watches evidence
 * being gathered rather than a cursor blinking.
 */

import {
  ArrowUpRight,
  CheckCircle,
  Database,
  Ranking,
  Warning,
  WarningOctagon,
} from '@phosphor-icons/react/dist/ssr';
import Link from 'next/link';
import { motion, useReducedMotion } from 'motion/react';

import { Meta, ProseShimmer } from '@/components/primitives';
import { DURATION, EASE_OUT } from '@/lib/motion';
import { indicatorTitle, modelLabel, type Citation } from '@/lib/api';

export type ExchangeStatus = 'working' | 'verified' | 'retracted' | 'error';

export interface ToolStep {
  name: string;
  summary: string;
  ok: boolean;
}

export interface Exchange {
  id: number;
  question: string;
  text: string;
  citations: Citation[];
  tools: ToolStep[];
  status: ExchangeStatus;
  provider?: string | null;
  score?: number | null;
  cached?: boolean;
  message?: string;
  /** Set when a provider failed part-way and another started the answer over. */
  restarted?: boolean;
}

/** The backend reports "none" when it declined without calling a model. */
function hasProvider(provider: string | null | undefined): provider is string {
  return Boolean(provider) && provider !== 'none';
}

export function ExchangeBlock({ exchange }: { exchange: Exchange }) {
  const working = exchange.status === 'working';
  const reduced = useReducedMotion() ?? false;

  return (
    /* `scroll-mt-20` clears the sticky topbar. A new question scrolled to the
     * top of the viewport otherwise lands underneath it. */
    <article className="scroll-mt-20 border-t border-[color:var(--hairline)] pt-8 first:border-t-0 first:pt-0">
      <h2 className="max-w-[52ch] text-[17px] font-medium leading-snug tracking-[-0.01em] text-ink">
        {exchange.question}
      </h2>

      {/* What it did before it said anything. */}
      {(exchange.tools.length > 0 || working) && (
        <ol className="mt-4 space-y-1.5">
          {exchange.tools.map((tool, index) => (
            <ToolRow key={`${tool.name}-${index}`} tool={tool} reduced={reduced} />
          ))}
          {working && <Pending hasTools={exchange.tools.length > 0} />}
        </ol>
      )}

      {exchange.restarted && (
        <p className="mt-3 flex items-start gap-2">
          <Warning aria-hidden weight="fill" className="mt-[3px] size-3.5 shrink-0 text-alert" />
          <Meta className="text-alert">
            a provider failed part-way through and another started the answer over
          </Meta>
        </p>
      )}

      <div aria-live="polite" aria-busy={working} className="mt-5">
        {working && exchange.text.length === 0 && <ProseShimmer lines={3} />}

        {exchange.text.length > 0 && (
          <motion.div
            initial={reduced ? false : { y: 6 }}
            animate={{ y: 0 }}
            transition={{ duration: DURATION.base, ease: EASE_OUT }}
          >
            <p className="max-w-[64ch] whitespace-pre-line text-[15px] leading-[1.75] text-ink-muted">
              <Marked text={exchange.text} count={exchange.citations.length} />
            </p>
          </motion.div>
        )}

        {exchange.status === 'retracted' && <Retracted reason={exchange.message} />}
        {exchange.status === 'error' && <Failed message={exchange.message} />}
      </div>

      {/* Two different things end up here and they must not read alike.
       *
       * An answer built from rows gets the verifier's verdict. But a question
       * outside the data is declined before any model is called — the sentence
       * is assembled from the tool errors, the provider comes back as "none",
       * and there are no figures in it at all. Announcing "every figure checked"
       * over a refusal that contains no figures claims a check that never
       * happened, and labelling the model as "none" is not a label. */}
      {exchange.status === 'verified' && (
        <p className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1">
          {exchange.citations.length > 0 ? (
            <>
              <span className="inline-flex items-center gap-1.5">
                <CheckCircle aria-hidden weight="fill" className="size-3.5 text-positive" />
                <Meta className="text-positive">
                  every figure checked against the rows it came from
                </Meta>
              </span>
              {hasProvider(exchange.provider) && <Meta>{modelLabel(exchange.provider)}</Meta>}
              {exchange.cached && <Meta>cached</Meta>}
            </>
          ) : (
            <Meta>
              declined before a model was called, so there is no figure here to check
            </Meta>
          )}
        </p>
      )}

      {exchange.citations.length > 0 && exchange.status !== 'error' && (
        <Sources citations={exchange.citations} exchangeId={exchange.id} />
      )}
    </article>
  );
}

function ToolRow({ tool, reduced }: { tool: ToolStep; reduced: boolean }) {
  const Glyph = tool.name === 'rank_countries' ? Ranking : Database;
  return (
    <motion.li
      initial={reduced ? false : { y: 4 }}
      animate={{ y: 0 }}
      transition={{ duration: DURATION.quick, ease: EASE_OUT }}
      className="flex items-start gap-2"
    >
      <Glyph
        aria-hidden
        weight="duotone"
        className={`mt-[2px] size-3.5 shrink-0 ${tool.ok ? 'text-signal-dim' : 'text-alert'}`}
      />
      <Meta className={tool.ok ? 'text-ink-muted' : 'text-alert'}>{tool.summary}</Meta>
    </motion.li>
  );
}

/** The wait, described rather than spun.
 *
 * Before the first tool result there is nothing to report except that a model is
 * deciding what to look up, so that is what it says. A bare spinner here would
 * be the design system's own anti-pattern. */
function Pending({ hasTools }: { hasTools: boolean }) {
  return (
    <li className="flex items-center gap-2">
      <span aria-hidden className="relative flex size-3.5 shrink-0 items-center justify-center">
        <span
          className="size-1.5 rounded-full bg-signal"
          style={{ animation: 'breathe 1.4s var(--ease-in-out) infinite' }}
        />
      </span>
      <Meta>{hasTools ? 'writing the answer' : 'choosing what to query'}</Meta>
    </li>
  );
}

function Retracted({ reason }: { reason?: string }) {
  return (
    <div
      className="mt-1 max-w-[64ch] rounded-md border-l-2 border-[color:var(--alert)] bg-[color:var(--plane-2)] py-3 pl-4 pr-4"
      role="status"
    >
      <p className="flex items-center gap-2 text-[13px] font-medium text-alert">
        <WarningOctagon aria-hidden weight="fill" className="size-4" />
        Withdrawn before it reached you
      </p>
      <p className="mt-1.5 text-[13px] leading-relaxed text-ink-muted">
        The answer quoted a figure that is not in the rows the query returned, so it was
        discarded rather than shown. This is the verifier working, not the system failing.
        {reason ? ` (${reason})` : ''}
      </p>
    </div>
  );
}

function Failed({ message }: { message?: string }) {
  return (
    <p className="flex max-w-[60ch] items-start gap-2 text-[13px] leading-relaxed text-ink-muted">
      <Warning aria-hidden weight="fill" className="mt-[3px] size-3.5 shrink-0 text-negative" />
      {message ?? 'Something went wrong.'}
    </p>
  );
}

/** Inline `[1]` markers, linked to the source they point at.
 *
 * The prompt requires them and the verifier splits them off before scoring, so
 * they are structure rather than prose. Rendering them as ordinary text leaves
 * the reader with a bracketed number and nowhere to go.
 */
function Marked({ text, count }: { text: string; count: number }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <>
      {parts.map((part, index) => {
        const match = /^\[(\d+)\]$/.exec(part);
        if (!match) return <span key={index}>{part}</span>;
        const n = Number(match[1]);
        if (n < 1 || n > count) return <span key={index}>{part}</span>;
        return (
          <a
            key={index}
            href={`#source-${n}`}
            className="mx-[1px] rounded-[3px] px-[3px] align-baseline text-[11px] font-medium text-signal transition-colors duration-150 hover:bg-[color:var(--signal-wash)]"
            style={{ fontFamily: 'var(--font-mono)' }}
          >
            {n}
          </a>
        );
      })}
    </>
  );
}

/** The rows the answer was built from.
 *
 * Each one names a country and a series and links to that exact pair, so a
 * reader can go and look at the line the figure came off. A ranking citation
 * says so, because "read every country" and "read one country" are different
 * claims and the distinction is the whole reason the ranking tool exists.
 */
function Sources({ citations, exchangeId }: { citations: Citation[]; exchangeId: number }) {
  return (
    <section aria-label="Sources" className="mt-5">
      <Meta className="uppercase tracking-[0.14em]">
        {citations.length} {citations.length === 1 ? 'source' : 'sources'}
      </Meta>
      <ul className="mt-2 grid gap-2 sm:grid-cols-2">
        {citations.map((citation) => (
          <li key={`${exchangeId}-${citation.index}`} id={`source-${citation.index}`}>
            <SourceCard citation={citation} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function SourceCard({ citation }: { citation: Citation }) {
  const ranked = citation.chunk_type === 'rank_countries';
  const body = (
    <>
      <span className="flex items-baseline justify-between gap-2">
        <span data-numeric className="text-[11px] text-signal">
          {citation.index}
        </span>
        {ranked && <Meta className="text-[10px] uppercase tracking-[0.12em]">whole field</Meta>}
      </span>
      <span className="mt-1 block truncate text-[13px] text-ink">
        {citation.country_name ?? citation.country_code ?? 'Reference'}
      </span>
      <span className="mt-0.5 block truncate">
        <Meta>{indicatorTitle(citation.indicator_name) || citation.indicator_code || '—'}</Meta>
      </span>
    </>
  );

  const shell =
    'block rounded-md border border-[color:var(--hairline)] bg-[color:var(--plane-2)] px-3 py-2.5 transition-colors duration-200';

  if (!citation.country_code) {
    return <span className={shell}>{body}</span>;
  }

  const href = citation.indicator_code
    ? `/country/${citation.country_code}?indicator=${encodeURIComponent(citation.indicator_code)}`
    : `/country/${citation.country_code}`;

  return (
    <Link href={href} className={`${shell} group hover:border-[color:var(--edge-strong)]`}>
      <span className="flex items-baseline justify-between gap-2">
        <span data-numeric className="text-[11px] text-signal">
          {citation.index}
        </span>
        <ArrowUpRight
          aria-hidden
          weight="bold"
          className="size-3 text-ink-dim transition-colors duration-200 group-hover:text-signal"
        />
      </span>
      <span className="mt-1 block truncate text-[13px] text-ink transition-colors duration-200 group-hover:text-signal">
        {citation.country_name ?? citation.country_code}
      </span>
      <span className="mt-0.5 block truncate">
        <Meta>
          {indicatorTitle(citation.indicator_name) || citation.indicator_code || '—'}
          {ranked && ' · whole field'}
        </Meta>
      </span>
    </Link>
  );
}
