/** Server-side proxy to the FastAPI intelligence endpoints.
 *
 * The Phase 2 pages are server components, so the backend origin never reaches
 * the client bundle and the browser never calls the API directly. The Phase 3 AI
 * panels have to fetch *after* paint — the design system forbids AI content
 * blocking a page load — which means the browser needs an endpoint of its own.
 * This is that endpoint, and it preserves the existing posture: same-origin from
 * the browser's point of view, `NEXT_PUBLIC_API_URL` still only read on the server.
 *
 * `ALLOWED` is an explicit allowlist rather than a prefix check. A catch-all
 * segment concatenated straight onto an upstream URL is an open proxy, and this
 * one is reachable by anyone who can load the site.
 */

import { NextRequest } from 'next/server';

import { apiUrl } from '@/lib/api';

const ALLOWED = new Set([
  'forecast',
  'vlm-interpret',
  'anomaly-explanations',
  'chat',
  'chat/stream',
]);

/** The upstream path, or null when it is not one this proxy is willing to forward. */
function resolve(segments: string[]): string | null {
  if (segments.length === 0) return null;
  // Routes are either `<name>` or `<name>/<arg>`; `chat/stream` is the one
  // two-segment name, so both shapes are checked against the allowlist.
  const twoSegmentName = segments.slice(0, 2).join('/');
  if (ALLOWED.has(twoSegmentName) && segments.length === 2) return twoSegmentName;
  if (!ALLOWED.has(segments[0])) return null;
  if (segments.length > 2) return null;
  return segments.join('/');
}

async function forward(request: NextRequest, segments: string[], body?: string) {
  const path = resolve(segments);
  if (path === null) {
    return new Response(JSON.stringify({ detail: 'Unknown endpoint.' }), {
      status: 404,
      headers: { 'content-type': 'application/json' },
    });
  }

  const search = request.nextUrl.search;
  const target = apiUrl(`/api/v1/${path}${search}`);

  try {
    const upstream = await fetch(target, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'content-type': 'application/json' },
      body,
      // AI responses are cached in Supabase by the backend; caching them again at
      // the edge would serve text whose groundedness verdict has expired.
      cache: 'no-store',
    });

    // Streamed straight through: buffering the chat response here would collapse
    // the token stream into one delivery and defeat the point of it.
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        'content-type': upstream.headers.get('content-type') ?? 'application/json',
        'cache-control': 'no-cache, no-transform',
      },
    });
  } catch {
    return new Response(
      JSON.stringify({ detail: 'The intelligence service is unreachable.' }),
      { status: 502, headers: { 'content-type': 'application/json' } },
    );
  }
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return forward(request, path);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return forward(request, path, await request.text());
}
