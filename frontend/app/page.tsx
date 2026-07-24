import { apiUrl, type HealthResponse } from '@/lib/api';

// Render at request time so the live backend check never runs during `next build`.
export const dynamic = 'force-dynamic';

async function fetchHealth(): Promise<HealthResponse | null> {
  try {
    const res = await fetch(apiUrl('/health'), { cache: 'no-store' });
    if (!res.ok) return null;
    return (await res.json()) as HealthResponse;
  } catch {
    return null;
  }
}

function Row({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div
      style={{ borderColor: 'var(--border)' }}
      className="flex items-center justify-between border-b py-2 last:border-b-0"
    >
      <span style={{ color: 'var(--text-secondary)' }} className="text-sm">
        {label}
      </span>
      <span
        style={{
          color: accent ? 'var(--accent)' : 'var(--text-primary)',
          fontFamily: 'var(--font-mono)',
        }}
        className="text-sm"
      >
        {value}
      </span>
    </div>
  );
}

export default async function Home() {
  const health = await fetchHealth();
  const online = health?.status === 'ok';

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-10 px-6 py-16">
      <header className="flex flex-col gap-4">
        <span
          style={{ color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}
          className="text-xs uppercase tracking-[0.3em]"
        >
          Phase 1 · Foundation
        </span>
        <h1 className="text-5xl font-bold tracking-tight">EconRadar</h1>
        <p style={{ color: 'var(--text-secondary)' }} className="max-w-xl text-lg leading-relaxed">
          AI-native economic intelligence — live World Bank, IMF, FRED &amp; BIS data with zero-shot
          forecasting, LLM narration, VLM chart interpretation, and RAG Q&amp;A. Free and open source.
        </p>
      </header>

      <section
        style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
        className="rounded-xl border p-6"
      >
        <div className="mb-4 flex items-center gap-3">
          <span
            aria-hidden
            style={{ background: online ? 'var(--positive)' : 'var(--negative)' }}
            className="inline-block h-2.5 w-2.5 rounded-full"
          />
          <h2 className="text-xl font-semibold">
            Backend status:{' '}
            <span style={{ color: online ? 'var(--positive)' : 'var(--negative)' }}>
              {online ? 'online' : 'unreachable'}
            </span>
          </h2>
        </div>

        {health ? (
          <div>
            <Row label="API version" value={health.version} accent />
            <Row label="Environment" value={health.environment} />
            <Row label="Database" value={health.database} />
            <Row label="Scheduler" value={health.scheduler} />
          </div>
        ) : (
          <p style={{ color: 'var(--text-tertiary)' }} className="text-sm leading-relaxed">
            No response from{' '}
            <code style={{ color: 'var(--text-secondary)' }}>{apiUrl('/health')}</code>. Set{' '}
            <code style={{ color: 'var(--text-secondary)' }}>NEXT_PUBLIC_API_URL</code> and make sure
            the FastAPI backend is running.
          </p>
        )}
      </section>

      <footer style={{ color: 'var(--text-tertiary)' }} className="text-xs">
        End-to-end skeleton: Vercel → Render → Supabase. The interactive world map, country profiles,
        and RAG chat arrive in Phase 2.
      </footer>
    </main>
  );
}
