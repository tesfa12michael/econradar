import Link from 'next/link';

import { ChatPanel } from '@/components/ChatPanel';

export const metadata = {
  title: 'Ask the data — EconRadar',
  description:
    'Ask questions about official macroeconomic data. Every figure is retrieved, cited and verified.',
};

export default function ChatPage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-6 px-6 py-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="rounded-sm text-sm underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2"
            style={{ color: 'var(--accent)', outlineColor: 'var(--accent)' }}
          >
            ← Map
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">Ask the data</h1>
        </div>
        <p className="text-xs" style={{ color: 'var(--text-tertiary)' }}>
          World Bank · IMF · FRED · BIS · WB DataBank
        </p>
      </header>

      <ChatPanel />
    </main>
  );
}
