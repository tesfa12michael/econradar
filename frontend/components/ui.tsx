/** Shared presentational primitives, styled from the design-system tokens.
 *
 * Skeletons rather than bare spinners: the design system bans a spinner in a blank
 * panel, so every loading surface matches the shape of what it is replacing.
 */

import Link from 'next/link';

import { sourceLabel } from '@/lib/api';

export function Card({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border p-5 ${className}`}
      style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
    >
      {children}
    </section>
  );
}

export function PanelHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-3 text-xl font-semibold" style={{ color: 'var(--text-primary)' }}>
      {children}
    </h2>
  );
}

/** Source attribution chip. Every displayed data point needs one. */
export function SourceChip({ source }: { source: string | null | undefined }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs"
      style={{ background: '#3B5998', color: '#F0F4FF' }}
    >
      {sourceLabel(source)}
    </span>
  );
}

/** Anomaly badge. Colour is never the sole conveyor — icon and text always accompany it. */
export function AnomalyBadge({
  deviationType,
  zScore,
}: {
  deviationType: string | null;
  zScore: number | null;
}) {
  const severe = zScore !== null && Math.abs(zScore) >= 3;
  const color = severe ? 'var(--warn)' : '#FB923C';
  const icon = deviationType === 'drop' ? '▼' : deviationType === 'spike' ? '▲' : '◆';
  const label =
    deviationType === 'structural_break' ? 'Structural break' : deviationType === 'drop' ? 'Drop' : 'Spike';
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs"
      style={{ borderColor: color, color }}
    >
      <span aria-hidden>{icon}</span>
      {label}
      {zScore !== null && (
        <span style={{ fontFamily: 'var(--font-mono)' }}>z={zScore.toFixed(1)}</span>
      )}
    </span>
  );
}

export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-md ${className}`}
      style={{ background: 'var(--bg-elevated)' }}
      aria-hidden
    />
  );
}

/** A clearly-labelled placeholder for a Phase 3 feature. */
export function ComingSoonPanel({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <Card>
      <div className="mb-2 flex items-center justify-between gap-3">
        <PanelHeading>{title}</PanelHeading>
        <span
          className="whitespace-nowrap rounded-full border px-2 py-0.5 text-xs"
          style={{ borderColor: 'var(--border)', color: 'var(--text-tertiary)' }}
        >
          Coming soon
        </span>
      </div>
      <p style={{ color: 'var(--text-secondary)' }} className="text-sm leading-relaxed">
        {description}
      </p>
      <div className="mt-4 space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-11/12" />
        <Skeleton className="h-3 w-4/6" />
      </div>
    </Card>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <p style={{ color: 'var(--text-secondary)' }} className="text-sm font-medium">
        {title}
      </p>
      {hint && (
        <p style={{ color: 'var(--text-tertiary)' }} className="max-w-sm text-xs leading-relaxed">
          {hint}
        </p>
      )}
    </div>
  );
}

export function CountryLink({
  code,
  name,
  children,
}: {
  code: string;
  name?: string | null;
  children?: React.ReactNode;
}) {
  return (
    <Link
      href={`/country/${code}`}
      className="rounded-sm underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2"
      style={{ color: 'var(--accent)', outlineColor: 'var(--accent)' }}
    >
      {children ?? name ?? code}
    </Link>
  );
}
