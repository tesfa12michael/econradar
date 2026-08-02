import { ChatPanel } from '@/components/ChatPanel';
import { TopBar } from '@/components/home/TopBar';
import {
  fetchJson,
  type AnomalyRecord,
  type SystemStatus,
} from '@/lib/api';

export const revalidate = 300;

export const metadata = {
  title: 'Ask the data',
  description:
    'Ask questions about official macroeconomic data. The agent queries the database for every figure, cites the rows it read, and withholds any answer whose numbers do not check out.',
};

export default async function ChatPage() {
  const [status, anomalies] = await Promise.all([
    fetchJson<SystemStatus>('/status'),
    fetchJson<AnomalyRecord[]>('/api/v1/anomalies?limit=40'),
  ]);

  /* One reading per series, same rule as the homepage feed: a month of policy
   * decisions flags a dozen countries at once, and three prompts about the same
   * central bank is one prompt repeated. */
  const seen = new Set<string>();
  const flagged: AnomalyRecord[] = [];
  for (const anomaly of anomalies ?? []) {
    const key = `${anomaly.country_code}:${anomaly.indicator_code}`;
    if (seen.has(key)) continue;
    seen.add(key);
    flagged.push(anomaly);
    if (flagged.length === 4) break;
  }

  return (
    <>
      <TopBar status={status?.status ?? null} current="chat" />
      <main id="main">
        <ChatPanel status={status} flagged={flagged} />
      </main>
    </>
  );
}
