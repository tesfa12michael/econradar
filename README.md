# EconRadar

**An AI-native economic intelligence dashboard — a free, open-source alternative to Bloomberg Terminal.**

EconRadar ingests live data from the World Bank, IMF, FRED, BIS, and the World Bank DataBank, runs
zero-shot time-series forecasting, and layers LLM narration, VLM chart interpretation, and
RAG-powered Q&A on top — turning raw economic indicators into plain-language insight. Built for
policymakers, analysts, and small businesses in data-sparse regions, and free for anyone with a
browser.

> **Status:** Phase 1 (Foundation). See [`PROGRESS.md`](PROGRESS.md) for the current build state.

---

## Architecture at a glance

```
World Bank / IMF / FRED / BIS  →  FastAPI ETL (connectors + APScheduler)
                                        │
                                  Supabase PostgreSQL (+ pgvector, partitioned time series)
                                        │
             ┌──────────────────────────┼──────────────────────────┐
        Forecasting                  LLM / VLM                    RAG
        (Chronos-2 →                 (Mistral → Groq →            (pgvector
         TimesFM → Stats)             OpenRouter; Gemini)          hybrid retrieval)
                                        │
                                  FastAPI REST API
                                        │
                                  Next.js 15 frontend (Vercel)
```

Full detail lives in [`docs/architecture.md`](docs/architecture.md).

## Monorepo layout

| Path | What lives here |
|---|---|
| [`frontend/`](frontend) | Next.js 15 (App Router, TypeScript) — world map, country profiles, RAG chat |
| [`backend/`](backend) | FastAPI (Python 3.12) — REST API, connectors, AI services, scheduler |
| [`backend/connectors/`](backend/connectors) | `BaseDataSourceConnector` + one class per data source |
| [`backend/services/`](backend/services) | `ForecastingService`, `LLMService`, `VLMService` |
| [`supabase/`](supabase) | SQL schema migration + seed data |
| [`docs/`](docs) | Strategy, architecture, features, design system specs |
| [`PROGRESS.md`](PROGRESS.md) | Current phase, last session summary, next goal |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Step-by-step provisioning & deploy checklist |

## Quickstart (local)

**Prerequisites:** Python 3.12 (3.13 works for Phase 1), Node.js 20+, a Supabase project.

```bash
# 1. Database — apply the schema to your Supabase project (see supabase/README.md)
#    then seed reference data.

# 2. Backend
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp ../.env.example .env                             # fill in DATABASE_URL etc.
uvicorn main:app --reload                           # http://localhost:8000/health

# 3. Frontend
cd ../frontend
npm install
cp .env.local.example .env.local                    # set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                                          # http://localhost:3000
```

To provision the cloud services (Supabase, Render, Vercel, UptimeRobot) and go live, follow
[`DEPLOYMENT.md`](DEPLOYMENT.md).

## Tech stack

Next.js 15 · TypeScript · FastAPI · Python 3.12 · Supabase PostgreSQL 15 + pgvector · APScheduler ·
MapLibre GL JS + deck.gl · Recharts · Chronos-2 / TimesFM / StatsForecast · Mistral / Groq /
OpenRouter · Gemini Flash / Qwen3-VL.

## License

[MIT](LICENSE) — free and open source.
