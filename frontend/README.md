# EconRadar frontend

Next.js 15 (App Router, TypeScript strict) + Tailwind CSS v4.

Phase 1 is an on-brand placeholder that live-checks the backend `/health` endpoint. The
interactive world map (MapLibre + deck.gl), country profiles (Recharts), and RAG chat land in
Phase 2 with shadcn/ui.

## Develop

```bash
npm install
cp .env.local.example .env.local     # set NEXT_PUBLIC_API_URL to your backend
npm run dev                          # http://localhost:3000
```

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Dev server |
| `npm run build` | Production build |
| `npm run lint` | ESLint (`next lint`) |
| `npm test` | Vitest unit tests |

## Conventions

- TypeScript strict mode; single quotes; **named exports only** (except Next.js `page`/`layout` files).
- Design tokens live in `app/globals.css` (see `docs/designsystem.md`). Dark-first.
