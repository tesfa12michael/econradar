'use client';

/** The economic agent's interface (feature 2.9).
 *
 * The streaming contract is the interesting part, and it is not the one it
 * looks like. A tool-calling turn is not a token stream (decision #38), so the
 * answer arrives whole rather than a character at a time; what streams is the
 * agent's *work* — one `tool` event per database query, then the citations
 * those queries produced, then the text, then a verdict on it.
 *
 * That last event is why the text is never presented as fact when it appears.
 * Verification runs on the reassembled answer, because a fabricated figure can
 * straddle two deltas (decision #27), so the arrival order is: draft, then
 * ruling. A retracted answer is replaced by an explanation of why it was
 * withheld, and it is never cached, so it cannot be re-served instantly.
 */

import { useCallback, useRef, useState } from 'react';

import { Composer } from '@/components/chat/Composer';
import { ExchangeBlock, type Exchange, type ToolStep } from '@/components/chat/Exchange';
import { Opening } from '@/components/chat/Opening';
import {
  aiUrl,
  type AnomalyRecord,
  type ChatTurn,
  type Citation,
  type SystemStatus,
} from '@/lib/api';

interface Props {
  status: SystemStatus | null;
  flagged: AnomalyRecord[];
}

export function ChatPanel({ status, flagged }: Props) {
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [busy, setBusy] = useState(false);
  const nextId = useRef(1);
  const latest = useRef<HTMLDivElement>(null);

  const ask = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || busy) return;

      // Four turns of context, assembled from what is already on screen. The
      // server trims to the same limit, so a crafted client cannot widen it.
      const history: ChatTurn[] = exchanges
        .filter((a) => a.status === 'verified')
        .flatMap((a) => [
          { role: 'user' as const, content: a.question },
          { role: 'assistant' as const, content: a.text },
        ])
        .slice(-8);

      const id = nextId.current++;
      setExchanges((prev) => [
        ...prev,
        { id, question: trimmed, text: '', citations: [], tools: [], status: 'working' },
      ]);
      setBusy(true);

      // Bring the new question to the top of the view once, then leave the
      // reader alone. Scrolling to the bottom on every event fights anyone
      // trying to read an answer while the next part of it arrives.
      requestAnimationFrame(() =>
        latest.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
      );

      const patch = (changes: Partial<Exchange>) =>
        setExchanges((prev) => prev.map((a) => (a.id === id ? { ...a, ...changes } : a)));

      try {
        const response = await fetch(aiUrl('chat/stream'), {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ question: trimmed, history }),
        });

        if (!response.ok || !response.body) {
          patch({ status: 'error', message: await refusalMessage(response) });
          return;
        }

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
              const step: ToolStep = {
                name: String(event.name ?? ''),
                summary: String(event.summary ?? ''),
                ok: event.ok !== false,
              };
              setExchanges((prev) =>
                prev.map((a) => (a.id === id ? { ...a, tools: [...a.tools, step] } : a)),
              );
            } else if (event.type === 'citations') {
              patch({ citations: (event.citations as Citation[]) ?? [] });
            } else if (event.type === 'token') {
              text += String(event.text ?? '');
              patch({ text });
            } else if (event.type === 'reset') {
              // A provider failed mid-answer and another is starting over.
              text = '';
              patch({ text, restarted: true });
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
              patch({
                status: 'error',
                message: String(event.message ?? 'Something went wrong.'),
              });
            }
          }
        }
      } catch {
        patch({ status: 'error', message: 'The answering service is unreachable.' });
      } finally {
        setBusy(false);
      }
    },
    [exchanges, busy],
  );

  return (
    <div className="flex min-h-[calc(100dvh-3.75rem)] flex-col">
      {/* `pb-40` clears the composer, which sticks to the bottom of the viewport
          once the conversation is taller than it. Without it the last answer
          reads through the blur behind the input. */}
      <div className="mx-auto w-full max-w-4xl flex-1 px-5 pb-40 pt-10 sm:px-6">
        {exchanges.length === 0 ? (
          <Opening status={status} flagged={flagged} onAsk={ask} />
        ) : (
          <div className="space-y-8">
            {exchanges.map((exchange, index) => (
              <div key={exchange.id} ref={index === exchanges.length - 1 ? latest : undefined}>
                <ExchangeBlock exchange={exchange} />
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="sticky bottom-0 z-[var(--z-sticky)]">
        {/* A gradient rather than a flat translucent bar: content passing under
            the composer fades out instead of showing through it at 20%. */}
        <div
          aria-hidden
          className="pointer-events-none h-10"
          style={{
            background: 'linear-gradient(to bottom, transparent, var(--plane-0) 92%)',
          }}
        />
        <div className="bg-[color:var(--plane-0)] pb-5">
          <div className="mx-auto w-full max-w-4xl px-5 sm:px-6">
            <Composer onAsk={ask} busy={busy} autoFocus={exchanges.length > 0} />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Turn a refusal into something a reader can act on.
 *
 * `POST /chat` carries three limits, a body cap and field bounds (decision
 * #43), and every one of them can reject a request before a model is reached.
 * Reporting all of them as "the stream is unavailable" tells a reader nothing
 * about whether to wait a minute, shorten the question, or come back tomorrow —
 * and `Retry-After` already carries the real answer.
 */
async function refusalMessage(response: Response): Promise<string> {
  if (response.status === 429) {
    const after = Number(response.headers.get('Retry-After'));
    if (Number.isFinite(after) && after > 0) {
      const wait =
        after < 90
          ? `${Math.ceil(after)} seconds`
          : after < 5400
            ? `${Math.round(after / 60)} minutes`
            : 'tomorrow';
      return `Too many questions from here just now. The next one can go in ${wait}. Asking costs model quota on a free tier, so the rate is capped rather than metered.`;
    }
    return 'Too many questions from here just now. Asking costs model quota on a free tier, so the rate is capped rather than metered.';
  }

  if (response.status === 413) return 'That question is too long to send. Try a shorter one.';
  if (response.status === 422) {
    return 'That question is longer than the field allows, or the conversation has grown past the four turns it keeps.';
  }
  if (response.status >= 500) return 'The answering service is not reachable right now.';
  return 'That question could not be sent.';
}
