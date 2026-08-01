'use client';

/** RAG Q&A chat (feature 2.2).
 *
 * Built on the existing `components/ui.tsx` primitives rather than shadcn/ui
 * (decision #26). designsystem.md specifies shadcn plus `cult/ui` chat blocks;
 * Phase 2 shipped neither, and adding Radix, CVA, tailwind-merge and a
 * components.json to the tree for one page — then re-theming the map, profile and
 * status pages onto a second token system to match — is a larger change than the
 * feature, on a dependency tree already carrying deferred advisories.
 *
 * The streaming contract is the interesting part. Tokens arrive before anything
 * has been verified, so a streaming answer is rendered explicitly as a draft:
 * dimmed, labelled "verifying", and not presented as fact. The terminal verdict
 * either promotes it or retracts it. That is decision #8 applied to a medium that
 * shows text before it is finished — the alternative, buffering silently until
 * verification, would throw away the streaming the design system asks for.
 */

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';

import { aiUrl, modelLabel, type Citation, type ChatTurn } from '@/lib/api';

import { Card, Skeleton } from './ui';

type Status = 'streaming' | 'verified' | 'retracted' | 'error';

/** One database query the agent ran on the way to its answer. */
interface ToolStep {
  name: string;
  summary: string;
  ok: boolean;
}

interface Answer {
  id: number;
  question: string;
  text: string;
  citations: Citation[];
  tools: ToolStep[];
  status: Status;
  provider?: string | null;
  score?: number | null;
  cached?: boolean;
  message?: string;
}

const EXAMPLES = [
  'How does inflation in Nigeria compare with Ghana and Kenya?',
  'Which countries have the highest government debt as a share of GDP?',
  'What happened to Brazilian policy rates in the 1990s?',
];

export function ChatPanel() {
  const [input, setInput] = useState('');
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [busy, setBusy] = useState(false);
  const nextId = useRef(1);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [answers]);

  const ask = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || busy) return;

      // Four turns of context, assembled from what is already on screen. The
      // server trims to the same limit, so a crafted client cannot widen it.
      const history: ChatTurn[] = answers
        .filter((a) => a.status === 'verified')
        .flatMap((a) => [
          { role: 'user' as const, content: a.question },
          { role: 'assistant' as const, content: a.text },
        ])
        .slice(-8);

      const id = nextId.current++;
      setAnswers((prev) => [
        ...prev,
        { id, question: trimmed, text: '', citations: [], tools: [], status: 'streaming' },
      ]);
      setInput('');
      setBusy(true);

      const patch = (changes: Partial<Answer>) =>
        setAnswers((prev) => prev.map((a) => (a.id === id ? { ...a, ...changes } : a)));

      try {
        const response = await fetch(aiUrl('chat/stream'), {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ question: trimmed, history }),
        });
        if (!response.ok || !response.body) throw new Error('stream unavailable');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let text = '';

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE frames are separated by a blank line; a frame can arrive split
          // across two reads, so only complete ones are consumed.
          const frames = buffer.split('\n\n');
          buffer = frames.pop() ?? '';

          for (const frame of frames) {
            const line = frame.split('\n').find((l) => l.startsWith('data:'));
            if (!line) continue;
            let event: Record<string, unknown>;
            try {
              event = JSON.parse(line.slice(5).trim());
            } catch {
              continue;
            }

            if (event.type === 'tool') {
              // The agent queries before it writes, so these arrive first and are
              // the only feedback during that phase. They also make the guarantee
              // visible: a ranking answer shows that every country was read.
              setAnswers((prev) =>
                prev.map((a) =>
                  a.id === id
                    ? {
                        ...a,
                        tools: [
                          ...a.tools,
                          {
                            name: String(event.name ?? ''),
                            summary: String(event.summary ?? ''),
                            ok: event.ok !== false,
                          },
                        ],
                      }
                    : a,
                ),
              );
            } else if (event.type === 'citations') {
              patch({ citations: (event.citations as Citation[]) ?? [] });
            } else if (event.type === 'token') {
              text += String(event.text ?? '');
              patch({ text });
            } else if (event.type === 'reset') {
              // A provider failed mid-answer and another is starting over.
              text = '';
              patch({ text });
            } else if (event.type === 'verdict') {
              patch({
                status: event.grounded ? 'verified' : 'retracted',
                provider: (event.provider as string) ?? null,
                score: (event.score as number) ?? null,
                cached: Boolean(event.cached),
                message: event.grounded ? undefined : (event.reason as string),
                text: event.grounded ? text : '',
              });
            } else if (event.type === 'error') {
              patch({ status: 'error', message: String(event.message ?? 'Something went wrong.') });
            }
          }
        }
      } catch {
        patch({ status: 'error', message: 'The answering service is unreachable.' });
      } finally {
        setBusy(false);
      }
    },
    [answers, busy],
  );

  return (
    <div className="flex w-full flex-col gap-5">
      {answers.length === 0 && (
        <Card>
          <p style={{ color: 'var(--text-secondary)' }} className="mb-3 text-sm leading-relaxed">
            Ask about any country and indicator EconRadar tracks. Every figure comes from a
            live query against the database — you can see which queries ran — and anything
            that cannot be verified against them is withheld rather than guessed.
          </p>
          <ul className="flex flex-col gap-2">
            {EXAMPLES.map((example) => (
              <li key={example}>
                <button
                  type="button"
                  onClick={() => ask(example)}
                  className="w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:opacity-80 focus-visible:outline focus-visible:outline-2"
                  style={{
                    borderColor: 'var(--border)',
                    color: 'var(--text-secondary)',
                    outlineColor: 'var(--accent)',
                  }}
                >
                  {example}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {answers.map((answer) => (
        <AnswerBlock key={answer.id} answer={answer} />
      ))}
      <div ref={endRef} />

      <form
        className="sticky bottom-4 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          ask(input);
        }}
      >
        <label htmlFor="chat-input" className="sr-only">
          Ask a question about the data
        </label>
        <input
          id="chat-input"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask about a country and an indicator…"
          disabled={busy}
          className="flex-1 rounded-xl border px-4 py-3 text-base focus-visible:outline focus-visible:outline-2"
          style={{
            background: 'var(--bg-card)',
            borderColor: 'var(--border)',
            color: 'var(--text-primary)',
            outlineColor: 'var(--accent)',
          }}
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-xl px-5 py-3 text-sm font-semibold transition-opacity disabled:opacity-40 focus-visible:outline focus-visible:outline-2"
          style={{ background: 'var(--accent)', color: '#04121B', outlineColor: 'var(--accent)' }}
        >
          {busy ? 'Asking…' : 'Ask'}
        </button>
      </form>
    </div>
  );
}

function AnswerBlock({ answer }: { answer: Answer }) {
  const streaming = answer.status === 'streaming';

  return (
    <div className="flex flex-col gap-3">
      <p
        className="self-end rounded-2xl px-4 py-2 text-sm"
        style={{ background: 'var(--bg-elevated)', color: 'var(--text-primary)' }}
      >
        {answer.question}
      </p>

      <Card>
        {answer.tools.length > 0 && (
          <ul className="mb-3 flex flex-col gap-1 text-xs">
            {answer.tools.map((tool, i) => (
              <li
                key={`${tool.name}-${i}`}
                style={{ color: tool.ok ? 'var(--text-tertiary)' : 'var(--warn)' }}
              >
                <span aria-hidden>{tool.ok ? '▸ ' : '! '}</span>
                {tool.summary}
              </li>
            ))}
          </ul>
        )}

        <div aria-live="polite" aria-busy={streaming}>
          {streaming && answer.text.length === 0 && (
            <div className="space-y-2">
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-10/12" />
              <Skeleton className="h-3 w-5/6" />
            </div>
          )}

          {answer.text.length > 0 && (
            <p
              className="text-base leading-relaxed whitespace-pre-line"
              style={{
                // Dimmed while unverified: the text is on screen but is not yet
                // being presented as fact.
                color: streaming ? 'var(--text-tertiary)' : 'var(--text-secondary)',
              }}
            >
              {answer.text}
            </p>
          )}

          {answer.status === 'retracted' && (
            <p className="text-sm leading-relaxed" style={{ color: 'var(--warn)' }}>
              <span aria-hidden>! </span>
              This answer was withdrawn: it cited a figure that is not in the retrieved
              records, so it was not shown.
              {answer.message ? ` (${answer.message})` : ''}
            </p>
          )}

          {answer.status === 'error' && (
            <p className="text-sm leading-relaxed" style={{ color: 'var(--negative)' }}>
              {answer.message}
            </p>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          {streaming && (
            <span
              className="rounded-full border px-2 py-0.5"
              style={{ borderColor: 'var(--border)', color: 'var(--text-tertiary)' }}
            >
              Verifying figures…
            </span>
          )}
          {answer.status === 'verified' && (
            <>
              <span
                className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5"
                style={{ borderColor: 'var(--positive)', color: 'var(--positive)' }}
              >
                <span aria-hidden>✓</span> Figures verified
              </span>
              {answer.provider && (
                <span
                  className="rounded-full px-2 py-0.5"
                  style={{ background: '#3B5998', color: '#F0F4FF' }}
                >
                  {modelLabel(answer.provider)}
                </span>
              )}
              {answer.cached && (
                <span style={{ color: 'var(--text-tertiary)' }}>cached</span>
              )}
            </>
          )}
        </div>

        {answer.citations.length > 0 && answer.status !== 'error' && (
          <div className="mt-4">
            <h3 className="mb-2 text-xs uppercase tracking-wide" style={{ color: 'var(--text-tertiary)' }}>
              Sources
            </h3>
            <ul className="flex flex-wrap gap-2">
              {answer.citations.map((citation) => (
                <li key={citation.index}>
                  <CitationCard citation={citation} />
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>
    </div>
  );
}

function CitationCard({ citation }: { citation: Citation }) {
  const label = [citation.country_name ?? citation.country_code, citation.indicator_name]
    .filter(Boolean)
    .join(' · ');
  const body = (
    <span className="flex flex-col gap-0.5">
      <span style={{ color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}>
        [{citation.index}]
      </span>
      <span style={{ color: 'var(--text-secondary)' }}>{label || 'Reference'}</span>
    </span>
  );

  const className =
    'block rounded-lg border px-3 py-2 text-xs transition-colors hover:opacity-80 focus-visible:outline focus-visible:outline-2';
  const style = { borderColor: 'var(--border)', outlineColor: 'var(--accent)' };

  if (!citation.country_code) {
    return (
      <span className={className} style={style}>
        {body}
      </span>
    );
  }

  const href = citation.indicator_code
    ? `/country/${citation.country_code}?indicator=${encodeURIComponent(citation.indicator_code)}`
    : `/country/${citation.country_code}`;

  return (
    <Link href={href} className={className} style={style}>
      {body}
    </Link>
  );
}
