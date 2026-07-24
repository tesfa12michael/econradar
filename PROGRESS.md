<!-- filename: PROGRESS.md -->
# Progress

> Read this file before doing anything else. Read `CLAUDE.md` and the `docs/` files
> for the current phase before touching code.

## Current Phase

Phase 1: Foundation

## Phase Status

In Progress — **mid-session review checkpoint** (code written, not yet verified end-to-end).

## Last Session Summary

**Date:** 2026-07-24
**Session type:** Phase 1 build — first coding session.

Paused at the user's request for a review before local verification and the frontend.

**Built (written + byte-compiles cleanly; NOT yet run against installed deps or a live DB):**
- Repo initialized (`git init`, `main` branch). Root files: `.gitignore`, `.gitattributes`,
  MIT `LICENSE`, `README.md`, `.env.example` (mirrors `docs/architecture.md` env vars).
- **Database (`supabase/`)** — full schema migration for all 10 tables; `time_series` as a
  RANGE-partitioned parent; two partitioning paths (`0003a` pg_partman primary, `0003b` manual
  fallback); reference seed (5 sources, 8 WB indicators); `country_profiles` seed of **217 real
  economies generated from the live World Bank registry** (`backend/scripts/generate_country_seed.py`).
- **Backend (`backend/`)** — FastAPI app (`main.py`) with lifespan-managed scheduler + CORS;
  `config.py` (all-optional settings), `db.py` (lazy psycopg3 async engine, health probe),
  `models.py` (ORM), `schemas.py` (incl. shared `TimeSeriesRecord`), `repositories.py`.
  Routers: `/health`, `/status`, `/api/v1/countries`, `/api/v1/sources`, `/api/v1/indicators/{cc}`.
- **Connectors** — `BaseDataSourceConnector` (fetch→normalize→validate→persist template with
  `pipeline_runs` + `etl_errors` logging, self-seeding source/indicator upserts, partition-safe
  time_series upsert) and the concrete **World Bank** connector (paginated, retry/backoff, handles
  null-value + aggregate-row edge cases). WB API response shapes verified live against the real API.
- **Services** — `ForecastingService` / `LLMService` / `VLMService` stubs that fix the authoritative
  fallback order (Phase 3 implements them).
- **Scheduler** — `AsyncIOScheduler` + `SQLAlchemyJobStore` (Supabase); one WB job using an
  add-if-absent pattern that demonstrates restart-persistence.

**NOT done yet (remaining in this session):** local verification (`pip install`, `ruff`, `pytest`,
live connector run), backend tests, the Next.js frontend, GitHub Actions CI, Render/Vercel/UptimeRobot
configs, `docs/features.md` status updates, and the `DEPLOYMENT.md` handoff checklist.

## Files Created or Modified

Root: `.gitignore`, `.gitattributes`, `LICENSE`, `README.md`, `.env.example`, `PROGRESS.md`.
`supabase/`: `README.md`, `migrations/0001…0003b`, `seeds/0004_seed_reference.sql`,
`seeds/0005_seed_country_profiles.sql`.
`backend/`: `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `config.py`, `db.py`,
`logging_config.py`, `models.py`, `schemas.py`, `repositories.py`, `main.py`,
`connectors/{__init__,base,world_bank}.py`, `services/{__init__,forecasting,llm,vlm}.py`,
`scheduler/{__init__,scheduler,jobs}.py`, `routers/{__init__,health,data}.py`,
`scripts/generate_country_seed.py`.

## New Dependencies (flagged per CLAUDE.md hard rule)

- **Backend runtime:** fastapi, uvicorn[standard], pydantic, pydantic-settings, SQLAlchemy,
  psycopg[binary], httpx, APScheduler.
- **Backend dev/test:** pytest, pytest-asyncio, ruff.
- **Frontend:** none added yet (Next.js scaffold is still pending).

## Key Decisions Made (to be mirrored into `docs/architecture.md` decision log at session end)

- **psycopg3 as the single Postgres driver** — one driver serves both the SQLAlchemy async API
  engine (`postgresql+psycopg`) and APScheduler's sync `SQLAlchemyJobStore`. Avoids asyncpg+psycopg2 sprawl.
- **time_series indexing** — a single `UNIQUE (country_code, indicator_id, date)` constraint backs
  both upsert and the documented `(…, date DESC)` lookup (a btree scans backward), so the separate
  DESC index in `architecture.md` was intentionally omitted as redundant. Composite PK `(id, date)`
  is required because the table is partitioned on `date`.
- **Two partitioning paths** — pg_partman primary + a guaranteed manual fallback, responding to the
  flagged "verify pg_partman at project creation" open question. Record which path you run.
- **Scheduler add-if-absent** — the WB job is only added when not already in the store, so a restart
  demonstrably reloads it from Postgres rather than recreating it.
- **country_profiles seed** — `imf_classification` is a documented heuristic (IMF WEO Advanced list +
  WB income group), not fetched IMF data. `population_bracket` left null (Phase 2 enrichment).
- **Phase 1 job scope** — a curated 20-country focus set × 8 annual indicators (see `config.py`) to
  keep free-tier ingestion light; broadened in Phase 2.

## Open Blockers

- **No cloud accounts/secrets yet** — Supabase project, Render, Vercel, UptimeRobot, and the GitHub
  remote all require the user. All code + configs are being written to hand off; deploy + the live
  end-to-end checkpoint cannot be completed by me. (`gh` CLI is not installed locally either.)
- **Local Python is 3.13/3.14, not the 3.12 target** — verification will run on 3.13; CI pins 3.12.
- **Nothing is verified yet** — `ruff`/`pytest`/`build` have not run; only byte-compilation has.

## Phase Progress Tracker

| Phase | Name | Status |
|---|---|---|
| 1 | Foundation | 🚧 In Progress |
| 2 | Core Feature(s) | ⬜ |
| 3 | Intelligence Layer | ⬜ |
| 4 | Polish & Production Readiness | ⬜ |
| 5+ | Stretch Goals (Optional) | ⬜ |

## Next Session Goal (remaining Phase 1 work, in order)

1. Backend tests (health/status, WB connector normalize+fetch, base validation) + `ruff check`.
2. Create venv (py3.13), `pip install`, run `ruff` + `pytest` until green. Verify WB connector live.
3. Scaffold the Next.js 15 frontend placeholder (on-brand) calling the backend; Vitest + lint + build.
4. GitHub Actions CI (py3.12 backend; Node frontend). `render.yaml` + Vercel config.
5. `DEPLOYMENT.md` handoff checklist (Supabase apply, Render/Vercel deploy, UptimeRobot, GitHub push).
6. Update `docs/features.md` statuses; mirror decisions above into `docs/architecture.md`.
7. Hand off cloud provisioning; complete the live checkpoint with the user.

## Completed Phases Log

None yet — Phase 1 in progress.

## Agent Instructions for Updating This File
<!-- Read before writing the updated file -->
- Replace the entire file at the end of every session — never append
- Update "Last Session Summary" with this session's work only
- Update "Next Session Goal" with an ordered task list for what logically comes next
- Add any new packages/dependencies to the running log in this file
- Log new architectural decisions in `docs/architecture.md` AND reference them here
- Keep the file concise — summarise, don't transcribe
- Always include the session date at the top of "Last Session Summary"
