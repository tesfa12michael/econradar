<!-- filename: agent_docs/design-system.md -->
# Design System

## Layout Pattern

**Map-Dominant Split-Panel Dashboard.** The world map is the hero — everything else is subordinate to it, not a standard sidebar-left/content-right admin shell.

```
Home:
┌─────────────────────────────────────────────────────────┐
│  TOPBAR — Logo | Indicator Selector | Global Search     │
├─────────────────────────────────────────────────────────┤
│              WORLD MAP (Full Width, 60vh)               │
│         Choropleth + Anomaly Overlay + Tooltips         │
├──────────────────────┬──────────────────────────────────┤
│  INSIGHT RAIL        │  GLOBAL STATS STRIP              │
│  Top anomalies       │  Selected indicator: world avg,  │
│  Recent updates      │  highest, lowest, most volatile  │
└──────────────────────┴──────────────────────────────────┘

Country Profile Page:
┌─────────────────────────────────────────────────────────┐
│  ← Back | Country Name + Flag | IMF Classification     │
├──────────────────────────┬──────────────────────────────┤
│                          │  LLM NARRATION PANEL         │
│   TIME-SERIES CHART      │  "Inflation in Nigeria…"     │
│   + FORECAST OVERLAY     ├──────────────────────────────┤
│   + CONFIDENCE BANDS     │  VLM CHART ANALYSIS PANEL    │
│                          │  "This chart shows a sharp   │
│                          │   inflection in Q3 2024…"    │
├──────────────────────────┴──────────────────────────────┤
│  INDICATOR SELECTOR TABS  |  ANOMALY BADGES STRIP       │
├─────────────────────────────────────────────────────────┤
│  KEY METRICS CARDS (GDP, Inflation, Trade Balance...)   │
└─────────────────────────────────────────────────────────┘

Chat / RAG Page:
┌─────────────────────────────────────────────────────────┐
│  Full-width centered chat interface                      │
│  Messages with citation cards (country / indicator /    │
│  date range chips below each answer)                    │
└─────────────────────────────────────────────────────────┘
```

**Rationale:** Strong economic dashboards organize around a spatial visualization combined with rankings, trends, and in-depth country profiles — this layout mirrors that proven pattern while layering AI narration and VLM interpretation directly into the profile view. The map is the entry point; everything flows from a click.

**Responsive behavior:** The map stays full-width on all screens. The split-panel below it collapses to a vertical stack on mobile — persistent layout on desktop, single-column flow on small viewports.

## Component Library

**Primary: shadcn/ui + Tailwind CSS v4.**

Copy-paste model means zero runtime dependencies; components like `DataTable`, `Sidebar`, `Card`, and `Chart` cover every dashboard pattern needed here. The dark theme uses shadcn's CSS variable design tokens (`background`, `foreground`, `card`, `popover`, `border`) so theming switches with zero flash.

| Need | Component Source |
|---|---|
| Sidebar, Topbar, Sheet (mobile) | shadcn/ui native |
| Cards, Badges, Tabs, Tooltips | shadcn/ui native |
| Data Tables (anomaly lists, indicator tables) | shadcn/ui DataTable (TanStack Table) |
| Charts (time-series, forecast overlays) | shadcn/ui Chart (Recharts under the hood) |
| Chat interface (RAG Q&A) | `cult/ui` AI blocks — shadcn-compatible chat primitives, streaming-ready |
| World Map | MapLibre GL JS + deck.gl (no shadcn equivalent) |
| Animations (transitions, skeleton loaders) | `tailwindcss-animate` (bundled with shadcn) |

**Alternatives rejected:** Material UI (heavy runtime, fights dark-mode customization), Ant Design (enterprise aesthetic clashes with the AI-native identity), Chakra UI (weaker Next.js App Router support in 2026), Mantine (a separate theming system that conflicts with Tailwind tokens).

## Color Palette

**Approach: True Dark + Single Accent Color + Semantic Status Colors.** Not a generic dark theme — designed specifically for a data-heavy geospatial tool where the map is the visual anchor and chart series must stay legible against dark surfaces. Inverting a light-mode chart palette produces an unreadable, neon-flavored result on dark backgrounds, so every chart color here is dark-first by design.

### Base Palette

| Role | Hex | Usage |
|---|---|---|
| Background — App | `#0A0F1E` | Full page background — deep navy, not pure black |
| Background — Card | `#111827` | Cards, panels, modals |
| Background — Elevated | `#1A2235` | Hovered cards, dropdowns, popovers |
| Border | `#1F2D45` | All borders — barely visible, never heavy |
| Text — Primary | `#F0F4FF` | Headlines, key values |
| Text — Secondary | `#8B9EC7` | Labels, captions, metadata |
| Text — Tertiary | `#4A5A7A` | Placeholder text, disabled states |

### Accent

| Role | Hex | Usage |
|---|---|---|
| Accent | `#00D4FF` | Interactive elements, selected states, active indicators, forecast lines |

Chosen deliberately: electric cyan-teal reads as "data intelligence," not "fintech" (green) or "security" (red) — the visual language of scientific data tools and AI systems.

### Semantic / Status Colors

| Status | Hex | Usage |
|---|---|---|
| Anomaly — Critical | `#F59E0B` | Severe anomaly badges, alert indicators |
| Anomaly — Watch | `#FB923C` | Moderate anomaly flags |
| Positive / Growth | `#34D399` | Positive trend indicators, GDP growth |
| Negative / Decline | `#F87171` | Negative trends, recession signals |
| Forecast | `#00D4FF99` | Confidence band fill (accent at 60% opacity) |
| Data Source Badge | `#3B5998` | Source attribution chips (WB, IMF, FRED, BIS) |

### Choropleth Map Palette (Dark-Optimized)

Sequential (single indicator, e.g., inflation intensity):
```
Low → #1A2235 → #1E4080 → #1A7ABF → #00A8D4 → #00D4FF → High
```
No-data countries render as `#1A2235` (the card background) — they recede without distracting.

Diverging (e.g., GDP growth, positive/negative):
```
Negative → #7F1D1D → #1A2235 (neutral) → #064E3B → Positive
```

**Light mode** is supported via shadcn's token system (one toggle, zero flash) but dark is the default and primary target — appropriate for a data-heavy tool where users spend extended time reviewing numbers and charts.

## Typography

**Approach:** Geometric sans-serif for prose, monospace for numbers — legibility at density.

| Role | Font | Why |
|---|---|---|
| Display / Headlines | Inter | De facto standard for data-heavy SaaS; excellent numeric rendering; shadcn/ui is designed around it. |
| Body / Narration Text | Inter (same) | LLM narration and RAG chat answers are paragraph-length — 15px/1.6 line-height reads well at that length. |
| Numeric / Data Values | JetBrains Mono | Monospace aligns numeric values vertically in tables and KPI cards, and visually distinguishes "data" from "prose." |

### Type Scale

| Level | Size | Weight | Usage |
|---|---|---|---|
| `text-4xl` | 36px | 700 | Country name on profile page |
| `text-2xl` | 24px | 600 | Section headings, KPI card values |
| `text-xl` | 20px | 600 | Panel headings (Narration, VLM Analysis) |
| `text-base` | 16px | 400 | Body text, LLM narration content |
| `text-sm` | 14px | 400 | Labels, captions, badge text, metadata |
| `text-xs` | 12px | 400 | Data source attribution, footnotes |
| `font-mono text-lg` | 18px | 600 | KPI numeric values |
| `font-mono text-sm` | 14px | 400 | Table cell numbers |

## Key User Flows

### Flow 1 — The Hiring Manager First Impression (World Map → Country Profile)

The most important flow — must work flawlessly in a 60-second live demo.

1. User lands on `/` — map renders immediately from cached data; indicator selector defaults to "GDP Growth (Annual %)"; anomaly-flagged countries pulse an amber badge; global stats strip shows world average/highest/lowest/most volatile.
2. User hovers a country — tooltip shows flag, name, current value, anomaly status; country highlights on hover.
3. User clicks a country — navigates to `/country/[code]`; skeleton loaders appear for chart/narration/VLM panels; historical chart loads first (direct DB query, fastest), forecast overlay fades in with confidence bands, narration streams in, VLM panel loads last (lowest priority, separately cached), anomaly badges populate.
4. User switches indicator — parallel fetch for the new series/forecast/narration; chart transitions smoothly; narration and VLM panels refresh with new context.
5. User clicks "Ask AI" — slides into the RAG Q&A panel on the same page with a pre-populated, editable prompt.

### Flow 2 — The RAG Q&A Interrogation (Chat Interface)

The most impressive demo moment for technical hiring managers.

1. User opens `/chat` (or the in-page panel) — centered interface, max-width 800px, placeholder example prompt.
2. User asks a question — hybrid retrieval (vector search + metadata filter) runs; streaming response begins within ~1s via the Groq speed layer.
3. Citation cards appear below the answer (source, indicator, country, value) — each is clickable and navigates to that country/indicator.
4. A follow-up question maintains conversation context (last 4 turns) and expands retrieval to any newly-referenced country.
5. Clicking a citation card navigates to the full country profile with that indicator pre-selected.

### Flow 3 — The Portfolio Reviewer (Public Status → Private Deep-Dive)

Demonstrates production thinking without exposing internals to the open internet.

1. Any visitor can reach `/status` (linked from the README/footer), no auth required — overall system status, last successful ingestion timestamp per source, aggregate 7-day AI cache hit rate (no per-model breakdown), RAG availability indicator, a monitored country/indicator count, and a static statement confirming groundedness verification is active.
2. A trusted reviewer who has been given a token directly (never via the repo or README) appends it to `/admin/health` for the full internal dashboard — per-source pipeline table, LLM usage table with provider/cache-hit breakdown, forecast job table, and visible fallback/rotation counts proving the resilience architecture works live.
3. Without a valid token, `/admin/health` simply refuses access — nothing about it hints that deeper internals exist beyond what `/status` already shows.

## Accessibility Baseline

**Target:** WCAG 2.1 Level AA throughout.

| Requirement | Implementation |
|---|---|
| Color contrast | All text on dark backgrounds meets 4.5:1 minimum. Accent `#00D4FF` on `#0A0F1E` = 8.2:1. Primary text `#F0F4FF` on card `#111827` = 14.3:1. |
| Color not the sole conveyor | Every anomaly badge pairs an icon and a text label with its color — never color alone. |
| Keyboard navigation | Map country selection, indicator tabs, chat input, and citation cards are all keyboard-navigable with visible focus rings. |
| ARIA labels | All icon-only buttons, map regions, and chart elements carry `aria-label` or `aria-describedby`. |
| Focus management | Opening the chat panel or a modal moves focus to its first interactive element. |
| Screen reader | Narration and VLM panels use `aria-live="polite"` so new content is announced as it loads. |
| Reduced motion | All animations (map hover, chart transitions, text streaming) respect `prefers-reduced-motion`. |
| Choropleth accessibility | Every map region's tooltip is reachable on keyboard focus, not just on mouse hover. |

## Do-Not List

Common anti-patterns Claude Code must never introduce for this project:

| Anti-Pattern | Why It's Banned Here |
|---|---|
| Inverted light-mode chart palette | Produces an unreadable, neon-flavored result on dark backgrounds — chart palettes must be designed dark-first. |
| Pure black (`#000000`) backgrounds | Causes harsh contrast and eye strain — use the near-black `#0A0F1E`. |
| Multiple accent colors | One accent (`#00D4FF`) only — status colors are semantic, never decorative. |
| Blocking page loads for AI content | Narration and VLM interpretation must load as non-blocking async overlays, never delay the chart or map. |
| Numbers generated by LLM in narration | The LLM narrates numbers already computed — it must never generate, estimate, or approximate a statistic. |
| Recharts for the world map | Recharts is for time-series only. MapLibre GL JS + deck.gl own all geographic rendering. |
| Unattributed data | Every displayed data point needs a source chip (World Bank / IMF / FRED / BIS / WB DataBank). |
| Sidebar navigation on the map page | The map needs full horizontal width — topbar navigation only on `/`. |
| Dark mode as a CSS override | Built into the design system via shadcn's token system from day one, not bolted on after. |
| Loading spinners without skeletons | Every content panel uses a skeleton loader matching the shape of what's loading — never a bare spinner in a blank panel. |
| Publicly linking or committing the `/admin/health` token | The token is shared directly with a trusted reviewer only — never in the README, never in the repo, never linked from any public page. |
