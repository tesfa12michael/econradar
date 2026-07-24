<!-- filename: DEMO_SCRIPT.md -->
# Demo Script

> **Status:** Parts 2 and 3 are complete — they're built from decisions already locked in `strategy.md` and `architecture.md`, so nothing about the eventual build changes them. Part 1 is intentionally left as a scaffold, not written in full: it's a script for the *finished* product, and Phase 1 hasn't started yet. Fill it in during Phase 4, once there's a real UI to click through.

---

## Part 1 — The Demo Walkthrough

**[PENDING — write this in Phase 4.]**

Writing this in full today would mean either restating `design-system.md`'s Key User Flows under a different heading, or guessing at UI details that don't exist as pixels yet — and if the build deviates from plan at all (it usually does, at least a little), a script written this early needs a rewrite anyway.

When you get here in Phase 4, build it from:

- `design-system.md`'s three confirmed Key User Flows — Hiring Manager First Impression, RAG Q&A Interrogation, Portfolio Reviewer — as the skeleton. Each flow's numbered steps map roughly 1:1 to a script beat.
- The actual, running product. Click through every flow yourself first, and note anywhere reality diverged from the plan.
- Real screenshots or a short screen recording per beat, especially useful if pairing this with `CASE_STUDY.md`.

For each step, fill in this template:

- **What to show:** the exact screen/action (e.g., "click Nigeria on the map")
- **What to say:** a script line, written the way you'd actually say it out loud
- **What to highlight:** the one thing in this moment a hiring manager should notice — a technical detail, a design choice, a number

Start with Flow 1 (it has to work flawlessly in a 60-second live demo), then Flow 2, then Flow 3.

---

## Part 2 — Architectural Talking Points

Pulled directly from the Key Technical Decisions Log in `agent_docs/architecture.md`. This is the cheat sheet for "walk me through your architecture."

**1. Full-stack architecture — FastAPI + Next.js, not Next.js API routes alone.**
I chose a separate FastAPI backend over Next.js API routes because any AI-adjacent system eventually needs Python's ML ecosystem — torch, transformers, pandas — and Next.js API routes simply can't run a HuggingFace model. In a production AI system, having the right runtime for inference matters more than keeping everything in one language.

**2. Time-series storage — native PostgreSQL partitioning, not TimescaleDB.**
I chose native partitioning over TimescaleDB because Timescale's relicensing under the TSL made it unavailable on new Supabase projects — a licensing conflict I only found by actually checking, not assuming. In production, verifying your dependencies' license terms matters more than defaulting to the "obvious" time-series tool.

**3. Vector store — Supabase pgvector, not a dedicated vector database.**
I chose pgvector inside the existing Postgres instance over Pinecone, Weaviate, or Qdrant because at this project's scale, one fewer service is one fewer failure point and one fewer cost surface. In production, operational simplicity matters more than using the trendiest vector-database name on your resume.

**4. Forecasting model — Chronos-2, self-hosted on CPU, not a hosted inference API.**
I chose Chronos-2 running self-hosted on CPU because it achieves state-of-the-art zero-shot accuracy while still running free on Render's tier — no GPU required. In production, knowing which foundation models genuinely fit your infrastructure constraints matters more than reaching for whatever's most hyped.

**5. Scheduler persistence — APScheduler with a database-backed jobstore, not in-memory.**
I chose to persist APScheduler's jobstore to Postgres because Render's free tier restarts periodically, and an in-memory scheduler would silently lose every job on restart. In production, a background job system that survives a restart matters more than one that just works in local dev.

**6. Map library — MapLibre GL JS + deck.gl, not Leaflet.**
I chose MapLibre plus deck.gl because deck.gl renders 195 country polygons with live data overlays at WebGL performance that DOM-based Leaflet can't match, and MapLibre is a zero-cost, tokenless fork of Mapbox. In production, rendering performance at real data scale matters more than picking the most familiar library.

**7. LLM architecture — multi-provider rotation, not a single provider.**
I chose a rotation — Mistral, then Groq, then OpenRouter — over locking into one LLM provider because any single free-tier API will rate-limit under real demo traffic, and I wanted the system to never go dark mid-interview. In production, graceful degradation under a rate limit matters more than the simplicity of one integration.

**8. LLM role boundary — narrates numbers, never generates them.**
I chose to make the LLM strictly a narrator of precomputed numbers, never a generator of them, because LLMs hallucinate statistics, and I didn't want to ship a dashboard that could confidently state a wrong number. In production, a groundedness guarantee enforced programmatically matters more than a more "natural-sounding" but unverifiable output.

**9. VLM pipeline — server-side rendering, not a client-side screenshot.**
I chose to render charts to PNG server-side with Plotly before sending them to the VLM, rather than capturing a client-side screenshot, because server-side rendering is deterministic — the model always sees a clean, consistent image regardless of a user's browser state. In production, reproducibility matters more than convenience.

**10. Embeddings — a self-hosted fallback, not API-only.**
I chose to add a self-hosted sentence-transformers fallback alongside the cloud embedding API because if the primary rate-limits, I didn't want the entire RAG pipeline to go offline. In production, a degraded-but-functional fallback matters more than an all-or-nothing dependency on one vendor.

---

## Part 3 — Portfolio Positioning

What this project proves about me as an AI Engineer / AI Automation Engineer / Applied AI candidate:

- I can ship a genuine end-to-end AI pipeline, not just call an API — heterogeneous data ingestion, validated ETL with non-silent failure logging, structured storage, and AI-ready output, all wired together and running in production.
- I understand retrieval-augmented generation beyond tutorial level — hybrid retrieval combining vector search and metadata filtering, grounded citations, and an honest fallback when there isn't enough data to answer.
- I can deploy foundation models in production under real constraints — zero-shot time-series forecasting running on free-tier CPU, with a genuine fallback cascade, not a GPU-backed demo that only runs on my machine.
- I think about AI systems the way production teams do, not just the way demos do — response caching, multi-provider rate-limit rotation, groundedness verification, and observability were designed in from day one, not bolted on after.
- I can integrate a vision-language model into a genuinely novel workflow — chart-to-narrative interpretation isn't a capability that shows up in comparable portfolios, and I built it, not just described it.
