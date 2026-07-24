# Deployment & Provisioning Checklist

Everything the codebase can't do itself — the cloud accounts, secrets, and the live
Phase 1 checkpoint. Work top to bottom. Items marked 🔑 need a value only you can create.

The end goal (Phase 1 checkpoint): **a public Vercel URL renders a page that calls a public
Render URL, which reads real World Bank data out of Supabase through one API endpoint — and the
scheduled job survives a manual backend restart. GitHub Actions is green on `main`.**

---

## 1. GitHub

- [ ] Create a new **public** repo (e.g. `econradar`).
- [ ] Add the remote and push (this local repo already has commits on `main`):
      ```bash
      git remote add origin https://github.com/<you>/econradar.git
      git push -u origin main
      ```
- [ ] Confirm the **CI** workflow runs and goes green (Actions tab). It lints + tests the
      backend (Python 3.12) and lints + builds + tests the frontend (Node 20).

## 2. Supabase (database)

- [ ] Create a new project. Note the region and the database password.
- [ ] **Verify `pg_partman` availability** (the one flagged unknown — see `docs/strategy.md`).
      In the SQL Editor: `create extension if not exists pg_partman schema partman;`
      - Works → use the pg_partman migration path (0003a).
      - Errors → use the manual fallback (0003b).
- [ ] Apply the SQL in order (SQL Editor or `psql`) per [`supabase/README.md`](supabase/README.md):
      `0001_extensions` → `0002_schema` → **one of** `0003a`/`0003b` → `0004_seed_reference`
      → `0005_seed_country_profiles`.
- [ ] Run the verification queries at the bottom of `supabase/README.md`
      (expect 10 tables, >0 partitions, 5 sources / 8 indicators / 217 countries).
- [ ] 🔑 Copy these for later: **Project URL**, **anon key**, **service_role key** (Settings → API),
      and the **connection string** (Settings → Database → Connection string → URI).
      Use the **direct** connection (port 5432) or the **session** pooler for `DATABASE_URL`
      — not the transaction pooler (6543).

## 3. Backend on Render

- [ ] New → **Blueprint**, point it at the repo. Render reads [`render.yaml`](render.yaml)
      (free web service, root `backend/`, health check `/health`).
- [ ] 🔑 Set the `sync: false` env vars in the Render dashboard:
      `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
      `ADMIN_HEALTH_TOKEN_HASH`, and `CORS_ORIGINS` (your Vercel URL, comma-separated).
- [ ] 🔑 Generate the admin token + hash (store the **hash**; share the raw token privately, never commit it):
      ```bash
      python -c "import hashlib,secrets; t=secrets.token_urlsafe(24); print('TOKEN:',t); print('HASH:',hashlib.sha256(t.encode()).hexdigest())"
      ```
- [ ] Deploy. Confirm `https://<your-backend>.onrender.com/health` returns
      `{"status":"ok","database":"connected", ...}`.
- [ ] **Populate real data** (one-off), then confirm it's served:
      ```bash
      # From the Render Shell, or locally with DATABASE_URL set, in backend/:
      python scripts/smoke_ingest.py
      # then:
      curl "https://<your-backend>.onrender.com/api/v1/indicators/NGA?code=NY.GDP.MKTP.KD.ZG"
      ```
      A non-empty `observations` array = real World Bank data flowing Supabase → API. ✅

## 4. Frontend on Vercel

- [ ] Import the repo. **Root Directory → `frontend`**. Framework auto-detects as Next.js.
- [ ] 🔑 Env var `NEXT_PUBLIC_API_URL` = your Render URL (e.g. `https://<your-backend>.onrender.com`).
- [ ] Deploy. The page should render **"Backend status: online"** with the live health details.
- [ ] Back in Render, make sure `CORS_ORIGINS` includes the final Vercel URL, then redeploy the backend.

## 5. Scheduler persistence check (Phase 1 checkpoint)

- [ ] After the backend has started once, confirm the job persisted to Postgres:
      ```sql
      select id, next_run_time from apscheduler_jobs;   -- expect a 'world_bank_refresh' row
      ```
- [ ] In Render, **Manual Deploy → Restart** the service. After it restarts, check the logs for
      `already present in persistent store — survived restart`, and re-run the query above — the
      row is still there. That proves the schedule survived the restart. ✅

## 6. UptimeRobot (keep-alive + monitoring)

- [ ] Monitor 1 — HTTP(s): `https://<your-backend>.onrender.com/health`, 5-minute interval
      (keeps the free Render service warm so the scheduler keeps firing).
- [ ] Monitor 2 — HTTP(s): your Supabase REST endpoint
      `https://<ref>.supabase.co/rest/v1/` with header `apikey: <anon key>` (or the project URL).

## 7. Final sign-off

- [ ] Vercel page renders and shows the backend **online**.
- [ ] `/api/v1/indicators/NGA?code=NY.GDP.MKTP.KD.ZG` returns real World Bank observations.
- [ ] Scheduler row survives a manual Render restart.
- [ ] GitHub Actions green on `main`.
- [ ] Record in `PROGRESS.md`: the live URLs and which partitioning path (0003a/0003b) you ran.

> Nothing here exposes a secret in the repo. The admin token is shared directly with reviewers;
> only its hash lives in an env var. See the "Do-Not List" in `docs/designsystem.md`.
