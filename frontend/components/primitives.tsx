/** The presentational vocabulary of EconRadar.
 *
 * Two rules shaped everything here.
 *
 * **A surface is not automatically a card.** The default is `plain` — spacing
 * and a rule — because most groupings on these pages are reading order, not
 * elevation, and a page of bordered boxes is the layout that says nothing about
 * its content. `raised` exists for the few surfaces that genuinely sit above
 * the page, and it gets its depth from a lit top edge rather than a drop
 * shadow, which is invisible on a near-black background.
 *
 * **Provenance is typography, not chrome.** Source, coverage, vintage and
 * measurement basis are set in the mono face at small size, so they read as
 * marginalia in a statistical publication rather than as a row of coloured
 * pills. The data carries its own paperwork; the paperwork should not shout.
 */

import Link from 'next/link';
import type { Icon as PhosphorIcon } from '@phosphor-icons/react';
import { ArrowDown, ArrowUp, Warning } from '@phosphor-icons/react/dist/ssr';

import { sourceLabel } from '@/lib/api';
import { cn } from '@/lib/utils';

/* ── Surfaces ─────────────────────────────────────────────────────────────── */

type SurfaceTone = 'plain' | 'raised' | 'glass';

const SURFACE: Record<SurfaceTone, string> = {
  plain: 'bg-transparent',
  raised:
    'rounded-lg border border-[color:var(--hairline)] bg-[color:var(--plane-2)] ' +
    'shadow-[inset_0_1px_0_var(--edge-lit)]',
  glass:
    'rounded-lg border border-[color:var(--edge)] bg-[color:var(--plane-glass)] ' +
    'shadow-[inset_0_1px_0_var(--edge-lit),0_18px_50px_-24px_rgb(0_0_0/0.9)] ' +
    'backdrop-blur-xl',
};

export function Panel({
  tone = 'plain',
  className,
  children,
  ...rest
}: React.ComponentProps<'section'> & { tone?: SurfaceTone }) {
  return (
    <section className={cn(SURFACE[tone], className)} {...rest}>
      {children}
    </section>
  );
}

/** A section heading and the line that qualifies it.
 *
 * The qualifier sits directly beneath the title rather than opposite it. Pushed
 * to the far edge of the column it reads as an unrelated fragment, and it is
 * doing the opposite job — "214 countries, latest reading each" is what stops
 * "Ranked worldwide" being a claim the page cannot support.
 *
 * No eyebrow above either of them. Where a section sits on the page already
 * says what kind of thing it is; a small tracked label repeating that is
 * scaffolding.
 */
export function SectionHead({
  title,
  meta,
  as: Tag = 'h2',
  className,
}: {
  title: React.ReactNode;
  meta?: React.ReactNode;
  as?: 'h1' | 'h2' | 'h3';
  className?: string;
}) {
  return (
    <div className={className}>
      <Tag className="text-[15px] font-medium tracking-tight text-ink">{title}</Tag>
      {meta ? <div className="mt-1 text-[12px] text-ink-dim">{meta}</div> : null}
    </div>
  );
}

export function Hairline({ className }: { className?: string }) {
  return <div role="presentation" className={cn('h-px w-full bg-[color:var(--hairline)]', className)} />;
}

/* ── Measured content ─────────────────────────────────────────────────────── */

/** A figure. Mono, tabular, and correct from the first frame it is painted.
 *
 * Nothing in EconRadar counts up to its value. This product's whole claim is
 * that a displayed number is one it can stand behind, and an animation that
 * runs through two dozen wrong numbers on the way to the right one contradicts
 * that for the sake of a flourish. Figures arrive by fading in; the digits are
 * true the entire time.
 */
export function Figure({
  children,
  size = 'md',
  tone = 'default',
  className,
}: {
  children: React.ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  tone?: 'default' | 'signal' | 'muted' | 'positive' | 'negative';
  className?: string;
}) {
  const sizes = {
    sm: 'text-[13px]',
    md: 'text-[15px]',
    lg: 'text-[22px] tracking-[-0.01em]',
    xl: 'text-[34px] leading-none tracking-[-0.02em]',
  };
  const tones = {
    default: 'text-ink',
    signal: 'text-signal',
    muted: 'text-ink-muted',
    positive: 'text-positive',
    negative: 'text-negative',
  };
  return (
    <span data-numeric className={cn('font-medium', sizes[size], tones[tone], className)}>
      {children}
    </span>
  );
}

/** The mono marginalia line: coverage counts, dates, codes, basis notes.
 *
 * 12px, which is `docs/designsystem.md`'s `text-xs` and its floor for
 * attribution and footnotes. This carries real content — how many countries a
 * series covers, which years it spans, what basis it is measured on — so it is
 * held at the smallest size the design system permits for text, not below it. */
export function Meta({ className, children, ...rest }: React.ComponentProps<'span'>) {
  return (
    <span
      data-numeric
      className={cn('text-[12px] leading-relaxed text-ink-dim', className)}
      {...rest}
    >
      {children}
    </span>
  );
}

/** Which agency published this figure. Every displayed value needs one. */
export function SourceMark({
  source,
  className,
}: {
  source: string | null | undefined;
  className?: string;
}) {
  return (
    <span
      data-numeric
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap text-[10px] uppercase tracking-[0.14em] text-ink-muted',
        className,
      )}
    >
      <span
        aria-hidden
        className="h-2.5 w-px"
        style={{ background: 'var(--attribution)', boxShadow: '0 0 0 1px rgb(59 89 152 / 0.35)' }}
      />
      {sourceLabel(source)}
    </span>
  );
}

/* ── Anomalies ────────────────────────────────────────────────────────────── */

interface AnomalyShape {
  deviationType: string | null;
  zScore: number | null;
}

/** Colour is never the only conveyor: every badge carries an icon and a word.
 *
 * A structural break has no Z-score — the statistic is undefined for a move out
 * of a zero-spread window, not merely small — so it shows no number rather than
 * a zero that would read as "barely anomalous".
 */
export function AnomalyBadge({
  deviationType,
  zScore,
  className,
}: AnomalyShape & { className?: string }) {
  const { label, Glyph, colour } = anomalyLook(deviationType, zScore);
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-sm px-1.5 py-0.5 text-[11px] font-medium',
        className,
      )}
      style={{ color: colour, background: `color-mix(in srgb, ${colour} 12%, transparent)` }}
    >
      <Glyph aria-hidden weight="bold" className="size-3" />
      {label}
      {zScore !== null && (
        <span data-numeric className="opacity-80">
          z {zScore > 0 ? '+' : ''}
          {zScore.toFixed(1)}
        </span>
      )}
    </span>
  );
}

export function anomalyLook(deviationType: string | null, zScore: number | null) {
  const severe = zScore !== null && Math.abs(zScore) >= 3;
  const colour = severe ? 'var(--alert)' : 'var(--alert-soft)';
  if (deviationType === 'drop') return { label: 'Drop', Glyph: ArrowDown as PhosphorIcon, colour };
  if (deviationType === 'spike') return { label: 'Spike', Glyph: ArrowUp as PhosphorIcon, colour };
  return { label: 'Structural break', Glyph: Warning as PhosphorIcon, colour };
}

/* ── States ───────────────────────────────────────────────────────────────── */

/** Skeletons breathe rather than blink, and match the shape of what they
 * replace — the design system bans a bare spinner in an empty panel. */
export function Shimmer({ className, style, ...rest }: React.ComponentProps<'div'>) {
  return (
    <div
      aria-hidden
      className={cn('rounded-sm bg-[color:var(--plane-3)]', className)}
      style={{ animation: 'breathe 1.8s var(--ease-in-out) infinite', ...style }}
      {...rest}
    />
  );
}

export function ProseShimmer({ lines = 4 }: { lines?: number }) {
  const widths = ['100%', '92%', '97%', '64%', '88%', '71%'];
  return (
    <div className="space-y-2.5">
      {Array.from({ length: lines }, (_, i) => (
        <Shimmer key={i} className="h-2.5" style={{ width: widths[i % widths.length] }} />
      ))}
    </div>
  );
}

/** An empty state says what would have been here and why it is not. It is
 * never a shrug. */
export function Empty({
  title,
  hint,
  className,
}: {
  title: string;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col items-start gap-1.5 py-8', className)}>
      <p className="text-sm font-medium text-ink-muted">{title}</p>
      {hint && <p className="max-w-[52ch] text-[13px] leading-relaxed text-ink-dim">{hint}</p>}
    </div>
  );
}

/* ── Navigation ───────────────────────────────────────────────────────────── */

export function CountryLink({
  code,
  name,
  indicator,
  className,
  children,
}: {
  code: string;
  name?: string | null;
  indicator?: string | null;
  className?: string;
  children?: React.ReactNode;
}) {
  const href = indicator
    ? `/country/${code}?indicator=${encodeURIComponent(indicator)}`
    : `/country/${code}`;
  return (
    <Link
      href={href}
      className={cn(
        'rounded-sm text-ink decoration-[color:var(--signal)] decoration-1 underline-offset-[3px]',
        'transition-colors duration-150 hover:text-signal hover:underline',
        className,
      )}
    >
      {children ?? name ?? code}
    </Link>
  );
}
