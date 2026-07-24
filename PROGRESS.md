<!-- filename: PROGRESS.md -->
# Progress

> Read this file before doing anything else. Read `CLAUDE.md` and the `docs/` files
> for the current phase before touching code.

## Current Phase

Phase 1: Foundation

## Phase Status

In Progress — **all Phase 1 code is built and locally verified; the live cloud deploy +
end-to-end checkpoint remain** (they require accounts/secrets only the maintainer can create).

## Last Session Summary

**Date:** 2026-07-24
**Session type:** Phase 1 build — first coding session (repo → local skeleton, fully verified).

Built the complete end-to-end skeleton and verified everything that can be verified without
cloud accounts. What's left is provisioning + deploy, scripted in `DEPLOYMENT.md`.

**Built & locally verified (green):**
- **Backend** — FastAPI app: `/health`, `/status`, `/api/v1/{countries,sources,indicators/{cc}}`
  reading from Supabase via a repository layer; lazy psycopg3 async engine; all-optional settings.
  `BaseDataSourceConnector` (fetch→normalize→validate→persist with `pipeline_runs`/`etl_errors`
  logging + self-seeding upserts) and the concrete **World Bank** connector (paginated, retry/
  backoff, null/aggregate edge cases). AI service stubs pin the fallback order. APScheduler +
  `SQLAlchemyJobStore` with an add-if-absent WB job. **Verified:** `ruff` clean, `ruff format`
  clean, **18 unit tests + 1 live World Bank API test pass** (Python 3.13).
- **Database** — all 10 tables; `time_series` RANGE-partitioned (pg_partman primary + manual
  fallback); reference seed (5 sources, 8 indicators) + **217 country_profiles from the live WB
  registry**. Byte-verified SQL; not yet applied to a live Supabase.
- **Frontend** — Next.js 15 (App Router, TS strict) + Tailwind v4 on-brand placeholder that
  live-checks the backend `/health`. **Verified:** `next lint` clean, `next build` succeeds
  (`/` is dynamic), **2/2 Vitest pass**.
- **CI/deploy** — `.github/workflows/ci.yml` (backend py3.12 ruff+pytest; frontend Node20
  lint+build+test), `render.yaml`, and `DEPLOYMENT.md` (full provisioning checklist).

**Not done (needs maintainer / next session):** create the GitHub remote + push; provision
Supabase and apply migrations; deploy backend (Render) + frontend (Vercel); UptimeRobot; then the
live checkpoint incl. the scheduler-restart persistence proof. All scripted in `DEPLOYMENT.md`.

## Files Created or Modified

Root: `.gitignore`, `.gitattributes`, `LICENSE`, `README.md`, `.env.example`, `DEPLOYMENT.md`,
`render.yaml`, `.github/workflows/ci.yml`, `PROGRESS.md`.
`supabase/`: `README.md`, `migrations/0001…0003b`, `seeds/0004…0005`.
`backend/`: `requirements*.txt`, `pyproject.toml`, `config.py`, `db.py`, `logging_config.py`,
`models.py`, `schemas.py`, `repositories.py`, `main.py`, `connectors/`, `services/`, `scheduler/`,
`routers/`, `scripts/{generate_country_seed,smoke_ingest}.py`, `tests/`.
`frontend/`: `package.json`, `tsconfig.json`, `next.config.ts`, `postcss.config.mjs`,
`vitest.config.ts`, `.eslintrc.json`, `app/`, `lib/`.
`docs/`: `architecture.md` (decisions 11–14), `features.md` (statuses).

Six local commits on `main`; **nothing pushed** (no remote yet).

## New Dependencies (flagged per CLAUDE.md hard rule)

- **Backend runtime:** fastapi, uvicorn[standard], pydantic, pydantic-settings, SQLAlchemy,
  psycopg[binary], httpx, APScheduler.
- **Backend dev:** pytest, pytest-asyncio, ruff.
- **Frontend:** next 15, react/react-dom 19, typescript, tailwindcss v4 + @tailwindcss/postcss,
  eslint 8 + eslint-config-next, vitest.

## Key Decisions Made (logged in `docs/architecture.md` §Key Technical Decisions, rows 11–14)

- psycopg3 as the single Postgres driver (async API + sync jobstore).
- `time_series`: one `UNIQUE (country_code, indicator_id, date)` backs upsert AND the latest-first
  lookup (btree scans backward) — the separate DESC index was omitted as redundant; composite PK
  `(id, date)` required by partitioning.
- Two partitioning paths (pg_partman primary + manual fallback) for the flagged availability risk.
- Scheduler add-if-absent, so a restart demonstrably reloads the job from Postgres.
- Seed: `imf_classification` is a documented heuristic; `population_bracket` null (Phase 2).
  Phase 1 job scope = 20 focus countries × 8 annual indicators (see `backend/config.py`).

## Open Blockers

- **Cloud accounts/secrets** — GitHub remote, Supabase, Render, Vercel, UptimeRobot all need the
  maintainer. `gh` is not installed locally. Everything is scripted in `DEPLOYMENT.md`.
- **`pg_partman` availability** must be verified at Supabase project creation (0003a vs 0003b).
- **Local Python is 3.13**, not the 3.12 target — CI pins 3.12; keep an eye out for version-specific
  behavior when deploying.
- Minor: `CLAUDE.md` still points deep-context reads at `agent_docs/`; the docs live in `docs/`.

## Phase Progress Tracker

| Phase | Name | Status |
|---|---|---|
| 1 | Foundation | 🚧 In Progress (code done + locally verified; live deploy pending) |
| 2 | Core Feature(s) | ⬜ |
| 3 | Intelligence Layer | ⬜ |
| 4 | Polish & Production Readiness | ⬜ |
| 5+ | Stretch Goals (Optional) | ⬜ |

## Next Session Goal

1. Work through `DEPLOYMENT.md`: push to GitHub (confirm CI green); provision Supabase (verify
   pg_partman, apply migrations + seeds); deploy backend (Render) and frontend (Vercel); set env vars.
2. Run `backend/scripts/smoke_ingest.py` to populate real World Bank data; confirm
   `GET /api/v1/indicators/NGA?code=NY.GDP.MKTP.KD.ZG` returns it.
3. Prove scheduler persistence across a manual Render restart; set up UptimeRobot.
4. Flip Phase 1 features to `[x]` in `docs/features.md`, record live URLs + partitioning path here,
   then begin Phase 2 (remaining connectors, world map, country profile shell).

## Completed Phases Log

None yet — Phase 1's checkpoint requires the live deploy, which is the next session's first task.

## Agent Instructions for Updating This File
<!-- Read before writing the updated file -->
- Replace the entire file at the end of every session — never append
- Update "Last Session Summary" with this session's work only
- Update "Next Session Goal" with an ordered task list for what logically comes next
- Add any new packages/dependencies to the running log in this file
- Log new architectural decisions in `docs/architecture.md` AND reference them here
- Keep the file concise — summarise, don't transcribe
- Always include the session date at the top of "Last Session Summary"
