'use client';

/** The input.
 *
 * Not a search bar and not a message bubble. A search bar promises a list of
 * results; a message bubble promises a conversation partner. This is neither —
 * it is a question put to a database with a model between, and the surface it
 * sits on says so: one panel, a lit top edge, and a line underneath stating what
 * happens to the answer before anyone sees it.
 *
 * The field grows with the question rather than scrolling inside a fixed box,
 * because a reader editing a two-line question should be able to see both lines.
 */

import { ArrowUp } from '@phosphor-icons/react/dist/ssr';
import { useEffect, useRef, useState } from 'react';

import { Meta } from '@/components/primitives';

const MAX_HEIGHT = 176;

export function Composer({
  onAsk,
  busy,
  autoFocus,
}: {
  onAsk: (question: string) => void;
  busy: boolean;
  autoFocus?: boolean;
}) {
  const [value, setValue] = useState('');
  const field = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const node = field.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  const submit = () => {
    const question = value.trim();
    if (!question || busy) return;
    onAsk(question);
    setValue('');
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div
        className="rounded-lg border border-[color:var(--edge)] bg-[color:var(--plane-2)] shadow-[inset_0_1px_0_var(--edge-lit)] transition-colors duration-200 focus-within:border-[color:var(--signal)]"
      >
        <label htmlFor="question" className="sr-only">
          Ask a question about the data
        </label>
        <div className="flex items-end gap-2 p-2.5 pl-4">
          <textarea
            id="question"
            ref={field}
            rows={1}
            value={value}
            autoFocus={autoFocus}
            disabled={busy}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              // Enter asks; Shift+Enter breaks the line. A question long enough
              // to need two lines is rare, and needing a modifier to send the
              // common case would be the wrong way round.
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="Which country has the highest government debt?"
            className="max-h-44 min-h-[1.75rem] w-full resize-none bg-transparent py-1 text-[15px] leading-relaxed text-ink outline-none placeholder:text-ink-dim disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={busy || value.trim().length === 0}
            aria-label="Ask"
            /* The press scales rather than moving: a button that shifts down by
               a pixel drags the composer's baseline with it. */
            className="flex size-8 shrink-0 items-center justify-center rounded-md bg-[color:var(--plane-3)] text-ink-dim transition-[background-color,color,transform] duration-200 enabled:hover:bg-[color:var(--signal)] enabled:hover:text-signal-ink enabled:active:scale-95 disabled:opacity-45"
          >
            <ArrowUp aria-hidden weight="bold" className="size-4" />
          </button>
        </div>
      </div>

      <p className="mt-2 px-1">
        <Meta>
          {busy
            ? 'querying the database'
            : 'answers are built from queries against the database, and every figure in them is checked against the rows it came from before it is shown'}
        </Meta>
      </p>
    </form>
  );
}
