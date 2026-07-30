# EconRadar frontend

Next.js 15 (App Router, TypeScript strict) + Tailwind CSS v4.

The interactive world map (deck.gl choropleth, no base map) and country profiles (Recharts)
landed in Phase 2. Forecasting, LLM narration and RAG chat arrive in Phase 3.

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
