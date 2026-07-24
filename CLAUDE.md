<!-- filename: CLAUDE.md -->
# CLAUDE.md

AI-native economic intelligence dashboard: live World Bank/IMF/FRED/BIS data, zero-shot forecasting, LLM narration, VLM chart interpretation, and RAG Q&A — free, open-source, built as an AI Engineer portfolio piece.

## Tech Stack

- **Frontend:** Next.js 15 (App Router), TypeScript 5.x
- **Backend:** FastAPI 0.115.x, Python 3.12
- **Database:** Supabase PostgreSQL 15 + pgvector (partitioned via `pg_partman`)
- **AI/ML:** Chronos-2 → TimesFM → StatsForecast (forecasting); Mistral → Groq → OpenRouter (LLM); Gemini Flash → Qwen3-VL (VLM)

## Critical Commands

```bash
# Frontend (/frontend)
npm install                # install
npm run dev                # run dev server
npm test                   # run tests
npm run lint                # lint
npm run build                # build

# Backend (/backend)
pip install -r requirements.txt   # install
uvicorn main:app --reload         # run dev server
pytest                            # run tests
ruff check .                      # lint

# Deploy
git push origin main       # triggers Vercel (frontend) + Render (backend) auto-deploy
```

**After any change, always run:** `npm run build && npm test` (frontend) or `pytest && ruff check .` (backend)

## Directory Map

- `/frontend` — Next.js app: world map, country profile pages, RAG chat UI
- `/backend` — FastAPI app: routes, connectors, AI services
- `/backend/connectors` — `BaseDataSourceConnector` + one class per data source
- `/backend/services` — `ForecastingService`, `LLMService`, `VLMService`
- `/agent_docs` — strategy, architecture, features, and design-system specs
- `PROGRESS.md` — current phase, last session summary, next session goal
- `CLAUDE.md` — this file

## Code Style

- Python: follow Ruff defaults, type hints on all function signatures.
- TypeScript: strict mode, single quotes, named exports only (except Next.js page files).

## For Deep Context, Read:

- **Why we're building this, the feature list, portfolio signal:** `agent_docs/strategy.md`
- **Tech stack rationale, system diagram, data flow, DB schema, decisions log:** `agent_docs/architecture.md`
- **Feature specs per phase, acceptance criteria, status tracking:** `agent_docs/features.md`
- **Layout, color palette, typography, user flows, accessibility, do-not list:** `agent_docs/design-system.md`
- **Where the project stands right now:** `PROGRESS.md`

## Hard Rules — Never Break These

- Never modify the database schema without logging the change in `PROGRESS.md`.
- Never install a new package/dependency without flagging it in `PROGRESS.md`.
- Never let an LLM generate, estimate, or approximate a number in narration — it only narrates precomputed values (see `architecture.md`'s groundedness rule).
- Never commit an API key, secret, or the `/admin/health` token to the repo.
- Never start a new phase before this one's checkpoint criteria (`PROGRESS.md`) are met.
- Never touch code before reading `PROGRESS.md` and this session's relevant `agent_docs/` files.
- Never put dynamic state (current phase, task status) in this file — that belongs in `PROGRESS.md`.
- Commit after each logical task step with a descriptive message — never bundle unrelated changes.
- Never push to `main` mid-phase without confirming checkpoint criteria in `PROGRESS.md`.
- The AI service fallback order is defined in `backend/services/` — never reorder or modify it without updating `architecture.md`.
