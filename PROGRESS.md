<!-- filename: PROGRESS.md -->
# Progress

> Read this file before doing anything else. Your goal for this session is defined in "Next Session Goal." Do not proceed until you have read `CLAUDE.md` and all `agent_docs/` files referenced for your current phase.

## Current Phase

Phase 1: Foundation

## Phase Status

Not Started

## Last Session Summary

**Date:** 2026-07-24
**Session type:** Blueprint / pre-build (no code written)

This project has not yet entered a build phase. Everything below was decided during the blueprint-creation process (intake → research → feature scoring → architecture → design system → phased build plan → artifact generation), before any repository or code existed.

- Defined the project: an open-source AI economic intelligence dashboard (World Bank/IMF/FRED/BIS/WB DataBank data, Chronos-2 forecasting, multi-provider LLM narration, VLM chart interpretation, RAG Q&A).
- Completed intake, competitive research, and a fully-scored 21-feature tiered list (see `agent_docs/strategy.md`).
- Confirmed the full tech stack, system architecture, data flow, technical decisions log, and database schema (see `agent_docs/architecture.md`).
- Confirmed the design system: map-dominant layout, shadcn/ui + Tailwind v4, dark palette with a single cyan-teal accent, Inter/JetBrains Mono typography, three key user flows, WCAG 2.1 AA baseline (see `agent_docs/design-system.md`).
- Sequenced the confirmed decisions into five build phases with checkpoints (see the phase breakdown in `agent_docs/features.md`).
- Completed sequential artifact generation (Section 7): all 8 artifacts now exist — `strategy.md`, `architecture.md`, `features.md`, `design-system.md`, `CLAUDE.md`, this file, `PHASE_1_PROMPT.md`, and `DEMO_SCRIPT.md`.
- `CLAUDE.md` received a follow-up edit after initial generation (still under 200 lines) — see Key Decisions Made below.

## Files Created or Modified

| File | What Changed |
|---|---|
| `agent_docs/strategy.md` | Created |
| `agent_docs/architecture.md` | Created |
| `agent_docs/features.md` | Created |
| `agent_docs/design-system.md` | Created |
| `CLAUDE.md` | Created; later updated with verification command, commit-discipline rules, fallback-cascade rule, Code Style section |
| `PROGRESS.md` | Created (this file); later updated to reflect Section 7 completion |
| `PHASE_1_PROMPT.md` | Created |
| `DEMO_SCRIPT.md` | Created — Part 1 intentionally scaffolded, not fully written |

## Key Decisions Made

Amendments made mid-session, beyond a straight-line run of the original blueprint template — logged here so they aren't mistaken for oversights later:

- Added a `country_profiles` table to the schema (static country reference data) to avoid joining large time-series tables just for a country name, and to give the RAG pipeline structured "world knowledge."
- Replaced a fully-public `/admin/health` with a hybrid approach: a curated public `/status` page (sanitized signals only) plus a private, token-gated `/admin/health` (full internals) — the token is shared directly with reviewers, never committed or linked publicly.
- Added a Phase 4 deliverable outside this repo's 8 canonical artifacts: a standalone `CASE_STUDY.md` for the portfolio website, built entirely in Phase 4 from real metrics/screenshots/challenges, sourced from `agent_docs/`, this file's decision history, and the original research conversation.
- Deferred `DEMO_SCRIPT.md` Part 1 (The Demo Walkthrough) to Phase 4: Parts 2 and 3 are complete now since they're built from already-locked decisions, but a script for the finished product can't honestly be written before Phase 1 has even started. Build Part 1 from `design-system.md`'s Key User Flows plus the actual running product once it exists.
- Added four items to `CLAUDE.md` after initial generation: a mandatory post-change verification command, two commit-discipline rules, a rule pinning the AI service fallback order to `backend/services/` (changes require updating `architecture.md`), and a Code Style section (Ruff defaults + type hints for Python; strict mode, single quotes, named exports for TypeScript).

## Open Blockers

- No accounts or keys exist yet: Supabase project, Render account, Vercel account, FRED API key, and Mistral/Groq/OpenRouter/Google AI Studio keys all need to be created, plus the custom subdomain pointed at Vercel, before Phase 1 can finish.
- `pg_partman` availability must be verified on a fresh Supabase project — the architecture assumes it's enabled, but this has not been confirmed hands-on (see `agent_docs/strategy.md`'s open questions).
- Mistral's free-tier terms and Google AI Studio's current rate limits should be re-checked before Phase 3 wires them in — both were flagged as possibly stale by build time.

## Phase Progress Tracker

| Phase | Name | Status |
|---|---|---|
| 1 | Foundation | ⬜ |
| 2 | Core Feature(s) | ⬜ |
| 3 | Intelligence Layer | ⬜ |
| 4 | Polish & Production Readiness | ⬜ |
| 5+ | Stretch Goals (Optional) | ⬜ |

## Next Session Goal

**Objective:** Scaffold the repository and deploy a working end-to-end skeleton, proving the full pipeline (fetch → validate → store → serve) with one real connector (World Bank).

1. Initialize the GitHub repo with the `/frontend`, `/backend`, `/agent_docs` monorepo structure.
2. Provision the Supabase project, enable `pgvector`, and run the full schema migration.
3. Scaffold and deploy the FastAPI backend (`/health` endpoint) to Render.
4. Scaffold and deploy the Next.js frontend (placeholder page) to Vercel.
5. Build `BaseDataSourceConnector` and the World Bank connector.
6. Wire APScheduler with a `SQLAlchemyJobStore` persisted to Supabase; verify it survives a restart.
7. Populate `country_profiles` with static reference data.
8. Set up GitHub Actions CI (lint + tests).
9. Configure UptimeRobot pings for Render and Supabase.
10. Run the post-change verification commands (`npm run build && npm test`; `pytest && ruff check .`).
11. Update this file before ending the session.

## Completed Phases Log

None yet — the project is at the blueprint stage; no build phase has started.

## Agent Instructions for Updating This File
<!-- Read before writing the updated file -->
- Replace the entire file at the end of every session — never append
- Update "Last Session Summary" with this session's work only
- Update "Next Session Goal" with an ordered task list for what logically comes next
- Add any new packages/dependencies to a running log in this file
- Log new architectural decisions in `agent_docs/architecture.md` AND reference them here
- Keep the file under 150 lines — summarise, don't transcribe
- Always include the session date at the top of "Last Session Summary"
