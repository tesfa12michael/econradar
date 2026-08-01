/** The live ribbon under the topbar.
 *
 * Every item on it is a figure the system currently holds, read from `/status`
 * and from the ranking of the indicator on screen. Nothing here is invented,
 * nothing is a headline, and nothing is a placeholder for a feed that does not
 * exist — a tape of fabricated urgency on a product whose entire claim is that
 * it does not fabricate would be the worst possible thing to put at the top of
 * the page.
 *
 * Restraint is the whole design: mono, one weight, one accent, 78 seconds for a
 * full pass, and it stops the moment a pointer or focus enters so the links on
 * it can actually be used.
 */

import Link from 'next/link';

import { Meta } from '@/components/primitives';

export interface TapeItem {
  label: string;
  value: string;
  href?: string;
  /** Marks the item as a live signal rather than a stock count. */
  live?: boolean;
}

export function LiveTape({ items }: { items: TapeItem[] }) {
  if (items.length === 0) return null;

  return (
    <div
      className="tape relative overflow-hidden border-b border-[color:var(--hairline)] bg-[color:var(--plane-1)]/70 backdrop-blur-sm"
      aria-label="Current holdings and latest ingestion"
    >
      {/* `w-max` on the track without `overflow-hidden` on this container makes
          the whole document as wide as two full passes of the tape, which is a
          horizontal scrollbar on every page. */}
      <div className="tape__track flex w-max">
        <Run items={items} />
        {/* A second pass, so the loop closes without a visible seam. Hidden
            from assistive technology, and removed outright under reduced
            motion, where the strip scrolls instead of moving. */}
        <div className="tape__echo flex" aria-hidden>
          <Run items={items} />
        </div>
      </div>

      {/* Feathered edges, so items enter and leave rather than being clipped. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-0 left-0 w-16"
        style={{ background: 'linear-gradient(to right, var(--plane-0), transparent)' }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-0 right-0 w-16"
        style={{ background: 'linear-gradient(to left, var(--plane-0), transparent)' }}
      />
    </div>
  );
}

function Run({ items }: { items: TapeItem[] }) {
  return (
    <>
      {items.map((item, i) => (
        <TapeCell key={`${item.label}-${i}`} item={item} />
      ))}
    </>
  );
}

function TapeCell({ item }: { item: TapeItem }) {
  const body = (
    <>
      {item.live && (
        <span
          aria-hidden
          className="size-1 rounded-full bg-signal"
          style={{ boxShadow: '0 0 6px var(--signal)' }}
        />
      )}
      <Meta className="uppercase tracking-[0.14em]">{item.label}</Meta>
      <span data-numeric className="text-[11px] text-ink">
        {item.value}
      </span>
    </>
  );

  const shell = 'flex items-center gap-2 whitespace-nowrap px-5 py-1.5';

  return (
    <span className="flex items-center">
      {item.href ? (
        <Link
          href={item.href}
          className={`${shell} rounded-sm transition-colors duration-200 hover:bg-[color:var(--plane-3)]`}
        >
          {body}
        </Link>
      ) : (
        <span className={shell}>{body}</span>
      )}
      <span aria-hidden className="h-2.5 w-px bg-[color:var(--edge)]" />
    </span>
  );
}
