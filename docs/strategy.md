<!-- filename: agent_docs/strategy.md -->
# Strategy

## Project Summary

An open-source, AI-native economic intelligence dashboard that ingests live data from the World Bank, IMF, FRED, BIS, and the World Bank DataBank, applies zero-shot time-series forecasting, and layers LLM narration, VLM chart interpretation, and RAG-powered Q&A on top to turn raw economic indicators into plain-language insight. It exists for policymakers, analysts, and small businesses in data-sparse regions (Caribbean, Central America, Sub-Saharan Africa) who are priced out of tools like Bloomberg Terminal, and for one specific secondary audience: hiring managers evaluating this as an AI Engineer / AI Automation Engineer / Applied AI portfolio piece.

## Differentiation Angle

This project is the only free, open-source economic intelligence platform that fuses live multi-institution data pipelines (World Bank, IMF, FRED, BIS, WB DataBank) with zero-shot time-series foundation model forecasting, VLM-powered chart interpretation, and RAG-grounded natural language Q&A — purpose-built for data-poor regions and accessible to anyone with a browser.

It is not a Grafana clone with an LLM bolted on. It is an AI-native economic reasoning system that happens to have a beautiful interface. No existing tool in the competitive set (IMF DataMapper, Bloomberg Terminal, CEIC, Trading Economics, Grafana/Tableau) combines all four of: live multi-source ingestion, foundation-model forecasting, LLM narration, and VLM chart reading.

## Portfolio Signal Summary

This project is built to prove specific, current (2026) AI Engineer hiring signals, not just to look polished:

- **End-to-end data pipeline** — messy, heterogeneous institutional APIs → validated ETL → structured time-series storage → AI-ready output, with non-silent failure logging.
- **Full RAG implementation** — hybrid retrieval (vector search + metadata filtering), not a toy "stuff it in the prompt" demo.
- **Foundation model deployment** — zero-shot Chronos-2 inference running in production on free-tier CPU, not a Jupyter notebook tutorial.
- **VLM integration** — a chart-to-narrative pipeline using open-weight vision-language models. Genuinely rare in portfolios at this level.
- **Production thinking** — LLM response caching, multi-provider rate-limit fallback, data validation, and observability, all designed in from the start rather than bolted on.
- **Visual storytelling** — a live, anomaly-flagged world map with forecast overlays that lands with technical and non-technical reviewers equally.
- **Open source, demo-ready** — public repo, professional subdomain, live at any moment with no setup required from a reviewer.

What separates a forgettable version of this project from a memorable one: most AI dashboard portfolios are a Streamlit app calling an OpenAI endpoint. This one is a full-stack system with a purpose-built multi-source ETL layer, a foundation-model forecasting engine with a real fallback cascade, a grounded RAG knowledge layer, a VLM chart interpreter, and a production-grade frontend — entirely free and open. That combination does not commonly appear in candidate portfolios.

## Signature Features

Three features carry the highest combined portfolio-impact score and are treated as non-negotiable — the project is not "done" in spirit without all three working together on a single country profile page:

| Feature | Score | Why it's the differentiator |
|---|---|---|
| **VLM Chart Interpretation** | 9.0 | No competitor does this. The single most novel capability in the entire build. |
| **Zero-Shot Forecasting Engine (Chronos-2)** | 8.7 | Foundation-model deployment for economic forecasting is rare in portfolios and runs free on CPU. |
| **RAG-Powered Economic Q&A** | 8.0 | RAG is the most in-demand AI engineering skill in 2026; hybrid retrieval + grounding + citation separates this from tutorial-tier RAG. |

## Full Tiered Feature List with Portfolio Impact Scores

Scoring: **I** = Impressiveness, **S** = Signal Strength, **E** = Effort-to-Payoff, each 1–10. **Final = (I + S + E) / 3.**

### Tier 1 — Core MVP

| # | Feature | Description | I | S | E | Final |
|---|---|---|---|---|---|---|
| 1.1 | Multi-Source Data Ingestion Pipeline | Plugin-style connectors for World Bank, IMF, FRED, BIS, and WB DataBank, each inheriting a shared base class. | 7 | 9 | 7 | **7.7** |
| 1.2 | ETL Validation, Cleaning & Failure Logging | Per-record validation with malformed records logged, never silently dropped. | 6 | 10 | 8 | **8.0** |
| 1.3 | Time-Series Storage (Supabase PostgreSQL) | Partitioned time-series tables with a metadata/catalog layer. | 6 | 8 | 9 | **7.7** |
| 1.4 | Zero-Shot Forecasting Engine | Chronos-2 → TimesFM → StatsForecast cascade producing 12-month quantile forecasts. | 10 | 9 | 7 | **8.7** ⭐ |
| 1.5 | LLM Narration Layer | Multi-provider rotation (Mistral → Groq → OpenRouter) narrates precomputed numbers in plain English. | 8 | 8 | 7 | **7.7** |
| 1.6 | Interactive World Map | Choropleth, clickable, anomaly-flagged, built on MapLibre GL JS + deck.gl. | 10 | 6 | 7 | **7.7** |
| 1.7 | Country Profile Page | History, forecast overlay, narration, and VLM panels in one composed view. | 8 | 7 | 8 | **7.7** |
| 1.8 | Statistical Anomaly Detection | Rolling Z-score / IQR flagging surfaced on the map and profile page. | 7 | 7 | 8 | **7.3** |

### Tier 2 — Standard

| # | Feature | Description | I | S | E | Final |
|---|---|---|---|---|---|---|
| 2.1 | VLM Chart Interpretation Layer | Server-rendered chart images interpreted by Gemini Flash / Qwen3-VL. | 10 | 10 | 7 | **9.0** ⭐ |
| 2.2 | RAG-Powered Economic Q&A | Hybrid retrieval chat interface with grounded, cited answers. | 9 | 10 | 5 | **8.0** ⭐ |
| 2.3 | LLM-Grounded Anomaly Explanations | Anomalies get a narrated, hallucination-guarded explanation. | 8 | 9 | 7 | **8.0** |
| 2.4 | Scheduled Data Refresh | Per-source cadence via APScheduler, persisted to survive restarts. | 6 | 8 | 8 | **7.3** |
| 2.5 | LLM Response Caching Layer | Composite-key caching for narration and VLM output; extends free-tier quota life. | 5 | 9 | 8 | **7.3** |
| 2.6 | Observability & Pipeline Health Dashboard | Hybrid public `/status` + private token-gated `/admin/health`. | 6 | 10 | 6 | **7.3** |
| 2.7 | Multi-Indicator Comparison View | Side-by-side, multi-country, multi-indicator charting. | 7 | 5 | 7 | **6.3** |

### Tier 3 — Stretch Goals

| # | Feature | One-line description | I | S | E | Final |
|---|---|---|---|---|---|---|
| 3.1 | Multi-Model Forecasting Ensemble | Backtested, weighted blend of Chronos-2, TimesFM, and StatsForecast outputs. | 9 | 9 | 4 | **7.3** |
| 3.2 | OECD & Eurostat Connector Activation | Activates the pre-built plugin slots for OECD and EU member-state data. | 7 | 7 | 7 | **7.0** |
| 3.3 | AI-Generated Country Economic Report (PDF) | One-click, LLM-orchestrated downloadable briefing document. | 9 | 7 | 6 | **7.3** |
| 3.4 | Public REST API Endpoint | Versioned, rate-limited, documented API turning the dashboard into a platform. | 9 | 8 | 5 | **7.3** |
| 3.5 | User Alert Subscriptions | Webhook/email notification on anomaly detection via Supabase Edge Functions. | 8 | 7 | 5 | **6.7** |
| 3.6 | Aurora TSFM Integration | Experimental fourth forecasting model from ICLR 2026; monitor, don't commit yet. | 10 | 9 | 3 | **7.3** |

### Consolidated Scorecard (all features, ranked by Final Score)

| Rank | Feature | Tier | Final |
|---|---|---|---|
| 1 | 2.1 VLM Chart Interpretation Layer | Standard | 9.0 |
| 2 | 1.4 Zero-Shot Forecasting Engine | MVP | 8.7 |
| 3 | 2.2 RAG-Powered Economic Q&A | Standard | 8.0 |
| 3 | 2.3 LLM-Grounded Anomaly Explanations | Standard | 8.0 |
| 3 | 1.2 ETL Validation & Failure Logging | MVP | 8.0 |
| 6 | 1.1 Multi-Source Data Ingestion | MVP | 7.7 |
| 6 | 1.3 Time-Series Storage | MVP | 7.7 |
| 6 | 1.5 LLM Narration Layer | MVP | 7.7 |
| 6 | 1.6 Interactive World Map | MVP | 7.7 |
| 6 | 1.7 Country Profile Page | MVP | 7.7 |
| 11 | 2.4 Scheduled Data Refresh | Standard | 7.3 |
| 11 | 2.5 LLM Response Caching | Standard | 7.3 |
| 11 | 2.6 Observability & Health Dashboard | Standard | 7.3 |
| 11 | 1.8 Statistical Anomaly Detection | MVP | 7.3 |
| 11 | 3.1 Multi-Model Forecasting Ensemble | Stretch | 7.3 |
| 11 | 3.3 AI-Generated PDF Country Report | Stretch | 7.3 |
| 11 | 3.4 Public REST API Endpoint | Stretch | 7.3 |
| 11 | 3.6 Aurora TSFM Integration | Stretch | 7.3 |
| 19 | 3.2 OECD/Eurostat Connector Activation | Stretch | 7.0 |
| 20 | 3.5 User Alert Subscriptions | Stretch | 6.7 |
| 21 | 2.7 Multi-Indicator Comparison View | Standard | 6.3 |

## Downstream Portfolio Deliverable (Not Part of This Repo's Build Artifacts)

A deep, standalone case-study PDF for the portfolio website is planned — distinct from this repo's README and from `DEMO_SCRIPT.md` (which is a live-narration script, not a document meant to be read alone). Per the confirmed build plan, it is built entirely in **Phase 4**, once real metrics, screenshots, and build challenges exist to document. Its source material is intentionally broad: this document, the complete `agent_docs/` set, the full `PROGRESS.md` decision history accumulated from Phase 1 onward, and the original research conversation that produced this blueprint. Whoever builds it in Phase 4 should pull from `PROGRESS.md`'s decision log first — that log exists specifically so this document's reasoning survives even in a fresh session with no memory of how we got here.

## Open Strategic Questions & Assumptions

These were either explicitly flagged as unresolved during research, or are assumptions made in the absence of certainty. None of them block building — they're logged here so nobody re-litigates a settled question or, worse, silently trusts an assumption that was only ever a best guess.

- **Mistral's free tier is disputed.** One source describes it as a genuinely permanent ~1B tokens/month allowance; another describes it as a time-limited trial that converts to paid. The architecture routes around this automatically (Groq → OpenRouter fallback), but treat Mistral as generous-but-unverified, not load-bearing, until confirmed at build time.
- **Gemini Flash's free-tier quota is a moving target.** December 2025 brought a 50–92% cut to Google AI Studio's free limits. The specific request-per-day numbers cited during research may already be stale by the time the VLM layer is built in Phase 3 — re-check current limits before wiring the integration, don't assume the researched numbers still hold.
- **NVIDIA NIM's free credits are finite** (evaluation-only ToS, a fixed credit pool at signup). Treat this provider as supplementary demo capacity only, never as a load-bearing path for real traffic.
- **TimescaleDB is confirmed unavailable** on new Supabase PostgreSQL 17+ projects due to a licensing conflict. This is a resolved pivot (native partitioning + `pg_partman`), documented here so it isn't mistakenly revisited as an open option later.
- **Chronos-2 defaults to the "mini" (9M-parameter) variant** for guaranteed free-tier CPU performance. This assumes "mini" forecast quality is good enough for a portfolio demo. It's deliberately exposed as the `CHRONOS2_MODEL_SIZE` environment variable specifically so this can be revisited without a code change if accuracy disappoints in practice.
- **No user authentication or accounts exist anywhere in the confirmed feature set.** This is assumed to be fully out of scope by design — a public, login-free tool. Flagged explicitly in case this assumption turns out to be wrong.
- **Render's free-tier cold start (~30–60s after 15 minutes idle) is mitigated, not eliminated,** by UptimeRobot pings. This is acceptable for portfolio-review traffic patterns and was never intended to hold up under real concurrent production load.
- **The Phase 4 case study depends on documentation discipline across every phase**, not just on this document. If `PROGRESS.md`'s decision log is allowed to go thin during Phases 1–3, the case study will have less to work with than intended — this is a forward dependency, not a current blocker.
