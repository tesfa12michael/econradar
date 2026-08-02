# EconRadar frontend — handoff

Written 2026-08-02, at the end of the UI/UX redesign. Read this before touching
anything in `frontend/`. It is the whole story in one sitting: what exists, why
it is shaped this way, what was deliberately left out, and the traps.

---

## 1. What this frontend is

Three pages over a FastAPI backend that holds ~204,000 macroeconomic
observations from five statistical agencies:

| Route | What it is |
|---|---|
| `/` | The world map, and everything the current indicator implies |
| `/country/[code]` | One country, one series, in depth |
| `/chat` | An agent that queries the database to answer questions |

There is a fourth route the product expects and **does not have yet**: `/status`.
It is linked from the topbar and the footer, and it currently 404s. See §9.

**The backend is not ours to change.** Every API is stable and documented in
`docs/architecture.md` and `docs/features.md`. The redesign touched nothing
outside `frontend/`, and neither should the next one unless that is the task.

### The audience, and what follows from it

Two audiences at once: people who want to look something up, and hiring managers
evaluating the engineering. That second audience is why the interface *shows its
work* — the queries the agent ran, the coverage of a series, the fact that a
ranking read all 194 countries. A dashboard that hides its provenance is a nicer
picture and a worse portfolio piece.

---

## 2. The design thesis, in one paragraph

The old UI was not ugly. It was **anonymous**: every section was a rounded
rectangle with a 1px border on `#111827`, `p-5`, `gap-5`. That is the template
everyone gets. What this product actually is, is a system whose entire
engineering personality is *refusing to state what it cannot verify* — the
verifier retracts answers, the agent refuses superlatives it has not ranked for,
the map paints "no data" in a reserved colour so it can never be misread as zero.
So the design makes that the subject. **The ornament is the paperwork**: coverage
counts, observation vintages, measurement bases, source marks, "194 countries
ranked", "series begins 1991". All of it is true, all of it already existed in
the API, and none of it appears on anybody else's portfolio dashboard.

Everything below follows from that one decision.

---

## 3. The token system

Everything lives in `app/globals.css` under `:root`, exposed to Tailwind v4 via
`@theme inline`. There is no `tailwind.config.js` — v4 does not need one.

### Surfaces are a depth ramp, not a set of colours

`--plane-0` (the app background, `#0A0F1E`) → `--plane-1` → `--plane-2` (cards)
→ `--plane-3` (elevated) → `--plane-glass` (translucent, for the few things that
genuinely float over the map or the chart).

`docs/designsystem.md` specifies three surfaces and one border. That is enough
for flat cards and not enough for an interface that layers, so the ramp gained an
intermediate plane and a translucent one. **Elevation reads through
`--edge-lit`** — a 1px highlight along a surface's top edge. A drop shadow is
invisible on a near-black background; a lit edge is not.

### Lines

`--hairline` divides content inside a surface. `--edge` bounds a surface.
`--edge-strong` is for a border that has to be seen. If a 1px rule looks like it
is not rendering, it is probably `--hairline` on `--plane-0` — that pairing is
deliberately almost invisible, and it caught us once already (the chart's summary
row).

### The accent is `--signal`, not `--accent`

The brand cyan `#00D4FF` is `--signal`. **`--accent` belongs to shadcn**, where
it means "hover surface". Aliasing shadcn's `--accent` to electric cyan would
turn every hover state in the library into a flare. If you add a shadcn
component and it looks wrong, check which of the two you reached for.

`--signal` means live, selected, or interactive. Nothing else. Amber
(`--alert`) means a flagged observation and is **the only colour permitted to
glow**, because a glow here means "look at this".

### Ink has four steps and only three are readable

`--ink` → `--ink-muted` → `--ink-dim` → `--ink-faint`.

`--ink-dim` (`#7C90B8`) was added during the redesign. The design system's third
text colour, `#4A5A7A`, is 2.6:1 on the card surface — it fails WCAG AA
everywhere it carries content, and it was carrying content. `--ink-faint` is now
what the document says it is: **placeholders and disabled states, never content**.
If you find yourself typing `text-ink-faint` on something a person is meant to
read, use `--ink-dim`.

### Radius, motion, layers

Radius tops out at 14px; nothing on a surface is more rounded than that.
Durations and easings are in `--dur-*` and `--ease-*`, mirrored in
`lib/motion.ts` for the JS side so a chart drawing itself and a panel arriving
feel like one system. Z-index is a **named scale** (`--z-base` … `--z-tooltip`);
do not write an arbitrary `z-50`.

### Extending it

Add the raw value under `:root`, then alias it in `@theme inline` as
`--color-<name>`. That second step is what makes `bg-<name>` and `text-<name>`
exist. Do not add a colour that duplicates a step already on the ramp — the ramp
is short on purpose.

---

## 4. Typography

**Geist** for prose and UI. **JetBrains Mono** for everything measured.

Both are loaded through `next/font/google` in `app/layout.tsx`. Before the
redesign they were named in the token file and **never actually loaded**, so
every page had been rendering in `system-ui` since Phase 2. That was a real bug,
not a style preference.

Geist rather than the Inter `docs/designsystem.md` names: that document gives one
reason, "shadcn/ui is designed around it", which stopped applying when decision
#26 dropped the library — and Inter is now the default face of essentially every
generated interface on the web. Recorded as decision #47 in `docs/architecture.md`.

**The bigger half of the decision is the mono.** JetBrains Mono is exactly what
the design system specifies, promoted from "numbers in tables" to *every measured
thing on the page*: figures, dates, country codes, coverage counts, axis labels,
source marks, ranks. Statistical agencies publish in fixed-width columns, so the
split falls where the subject already puts it — **the mono carries what was
measured, the sans carries what was written about it.** That division is what
gives the pages a voice and it costs nothing.

In practice: `<Meta>` and `<Figure>` from `components/primitives.tsx` set the
mono with tabular figures. Reach for those rather than hand-rolling a
`font-mono` class.

---

## 5. Motion, and the one rule that matters most

### Content must never be conditional on an animation having run

This is not a stylistic preference. It was measured failing three times during
the redesign, and it is the single thing most likely to be broken by someone
adding a nice effect.

- **Scroll reveals shipped 22 elements at `opacity: 0` in the server HTML.** With
  JavaScript off, the rankings rail and the flagged feed were invisible. With the
  tab hidden, `requestAnimationFrame` stops, the reveal froze at zero, and they
  stayed invisible.
- **The map paints every country *from* the no-data colour**, so a sweep that
  never ran left a blank world. Screenshotted in exactly that state.
- **Recharts renders an animating line by growing its `strokeDasharray` from
  zero**, so an animation that never runs is a chart with no line in it.

The fixes are structural, not defensive:

1. **Reveals are transform-only.** `riseVariants` in `lib/motion.ts` animates `y`
   and nothing else. The worst case is a section sitting eight pixels low. Do not
   add `opacity` back.
2. **Entrance animations check `document.visibilityState` before starting** and
   complete immediately if the document goes hidden part-way (`WorldMap`,
   `SeriesChart`).
3. **`data-reveal` + two overrides.** Every reveal carries the attribute;
   `globals.css` resets it under `prefers-reduced-motion`, and a `<noscript>`
   block in `app/layout.tsx` resets it unconditionally.

Before you ship any animation, ask: *if this never runs, is anything unreadable?*
If yes, restructure it.

### Cursor reactivity

One `pointermove` listener for the whole application, in
`components/atmosphere/PointerField.tsx`, published as Motion values.

**Cursor position must never be React state.** A `useState` holding the cursor
re-renders the tree on every mouse event, which is the most reliable way to make
a live-looking interface feel slow. The listener is coalesced to one write per
frame and is **not attached at all** for coarse pointers or reduced motion — the
values rest at centre, so consumers need no branch.

Consumers: `Atmosphere` (parallax at two rates — the different rates are the
whole reason the depth reads), `Spotlight` (writes CSS custom properties
directly, so light moves on the compositor), `Magnetic` (a few pixels of pull on
a control; large magnetism is a party trick that makes targets harder to hit).

### The background

Three fixed layers: two slow gradient blooms, a **graticule** — meridians and
parallels — and a vignette. The graticule is deliberate: this is a map product,
so the structural ornament is a map element rather than the square CSS grid
painted behind every dark landing page. Keep the vignette light; a heavy one
flattens the layers underneath back into the dead surface they exist to replace.

### One product-specific rule

**No figure ever counts up to its value.** The claim this product makes is that a
number on screen is one it can stand behind. An animation running through two
dozen wrong numbers to reach the right one contradicts that for a flourish.
Figures fade in, correct from the first painted frame.

---

## 6. Component libraries

**shadcn/ui is adopted, mapped onto EconRadar's tokens rather than its own.**
`components.json` points at `app/globals.css`, where shadcn's semantic names are
defined as *aliases* — `--primary` is the signal cyan, `--card` is `--plane-2`,
`--border` is the specified `#1F2D45`. There is no second palette and no `oklch`
block. A shadcn component drops in already wearing the design system.

This supersedes decision #26, which had rejected the library. #26's objection was
never to Radix — it was to importing a competing token system and re-theming
three working pages onto it. That cost is what the alias layer avoids. Recorded
as decision #46.

Installed: `button`, `badge`, `separator`, `skeleton`, `tooltip`, `popover`,
`command`, `dialog`, `scroll-area`. Add more with
`npx shadcn@latest add <name>` — it will respect `components.json`.

**Two things to know about the vendored components.** The registry ships Lucide
imports; both were rewritten to Phosphor, because the product uses **one icon
family**. And `CommandInput` renders its own search icon — wrapping it in your
own icon produces two (this happened).

`components/ui/` is shadcn's. `components/primitives.tsx` is ours. The legacy
`components/ui.tsx` from before the redesign is **gone**; if you find an import
of `@/components/ui` that is not a subpath, it is stale.

### Icons

`@phosphor-icons/react`, imported from `@phosphor-icons/react/dist/ssr` in server
components. `optimizePackageImports` is set in `next.config.ts` because the entry
point is a barrel over several thousand icons. **Never use a text glyph as an
icon** — `▲ ▼ ◆ ✓` render differently on every platform and cannot be themed.
That is what the old UI did.

---

## 7. The pages

### `/` — the map

`app/page.tsx` is a server component. It makes two waves of requests: the
indicator catalogue and `/status` first (both indicator-independent), then the
map, the anomalies and the ranking for whatever series is selected.

The composition: topbar → live tape → **map, full bleed** → a measured reading
column below it. Full-bleed plate, measured column: that is how a publication is
laid out, and it is why the lower half is `max-w-6xl` rather than edge to edge.

**Over the map, top-left**, sits a caption block: the series name, its coverage,
its measurement basis, and the note its publisher wrote about what it can be
compared with. On a wide screen it sits over the north Atlantic, where the
choropleth has nothing to say; below `lg` it stacks above the map, because
overlaying a paragraph on a small map ruins both. That comparability note is the
most useful sentence on the page and nothing was reading it before.

**Two endpoints reached the frontend for the first time here:**

- **`/api/v1/rankings`** — the answer to the Montenegro failure. A superlative is
  a claim about a dataset, so the rail shows five at the top, three at the
  bottom, and **the count of everything between**. A top-five list that hides its
  denominator is the same mistake in a nicer typeface. The same request also
  supplies every country's rank, which is what the map's hover panel shows.
- **`/api/v1/indicator-metadata`** — turns the `<select>` into a control that
  groups 23 series by concept, marks which is primary, and shows coverage and
  basis on every row. Three of those series measure unemployment in ways that are
  not interchangeable; a flat dropdown made choosing between them a coin toss.
  That is exactly the metric confusion decision #36 exists to prevent.

**The map** (`components/WorldMap.tsx`) is deck.gl with **no base map**. There
used to be a MapLibre canvas painting `#0A0F1E` behind it — the same colour as
the page — and it crashed the deployed site when v6 shipped a module worker
webpack never emitted (decision #20). Do not add a mapping library back.

The choropleth fills in west to east, each country easing from the no-data colour
as the front reaches its longitude (`lib/geo.ts` computes anchors from the
largest ring of each polygon — averaging all rings puts France in the Atlantic).
Amber markers sit on flagged countries: the design system asked for that and it
had never been built. Keyboard traversal moves between countries with data and
mirrors the hover panel into an `aria-live` region.

### `/country/[code]` — one series in depth

Reads chart → figures → what is being measured → what a model made of it. Data,
context, insight, both top-to-bottom and left-to-right.

**The chart** (`components/SeriesChart.tsx`) has three things on it that must be
distinguishable at a glance: what was observed (solid), what was flagged (amber
rings, drawn by the line's *own dot renderer* so they cannot drift out of
alignment with it), and what is projected (dashed, inside a band that fades as it
widens). The boundary between record and projection is an **explicit labelled
rule**, not something to infer from a line style.

Axis scaling is in `lib/chartScale.ts` and is tested. Recharts' default domain
put the floor at −45 against a series minimum of −8.42, spending a fifth of the
plot on empty space; `niceDomain` rounds outward from the data's own range
instead. **The baseline is deliberately not forced to zero** — zero-anchoring is
required of bar charts, where length encodes value. A line encodes position, so
anchoring a policy rate that moves between 4% and 8% to zero flattens it to
nothing.

**Series ordering matters more than it looks.** The API returns a country's
series sorted by indicator code, which put the IMF current-account balance at the
head of every profile in the product. `orderForCountry` in `lib/series.ts` ranks
by coverage with primaries first. Japan holds 21 series, so the rail shows ten
and puts the rest behind a native `<details>` — switching series has worked
**without JavaScript** since Phase 2 and that guarantee is preserved.

The AI panel is a card with a mono provenance line: `✓ figures checked · Gemini
Flash · cached`. The verdict is the point — the text is only worth reading
because something rejected the version that was wrong.

### `/chat` — the agent

`components/ChatPanel.tsx` orchestrates; `components/chat/` holds the parts.

**There is no typewriter to build.** A tool-calling turn is not a token stream
(decision #38): the answer arrives as a single `token` event. What streams is the
agent's *work*. The event order is `tool*` → `citations` → `token` → `verdict` →
`done`, and the UI renders it in that order, so a reader watches evidence being
gathered rather than a cursor blinking.

**Failed tool calls are shown.** Asked for the highest government debt, the
agent's first ranking call misses on the phrasing and its second lands on
`GGXWDG_NGDP` over 194 countries — both lines appear. An agent recovering is more
convincing than one that appears never to have erred.

**The empty state is where the architecture is stated.** It names the two tools
and says plainly that there is no web search and no general-knowledge tool, so a
figure the database does not hold has no path into an answer. That count *is* the
design, and a reader needs it before spending a question to find out. Everything
on it is live: holdings from `/status`, and four real detections that become real
questions when clicked.

Citations are cards linking to the exact country and series. A ranking citation
is marked **"whole field"**, because "read every country" and "read one row" are
different claims.

Two things the redesign fixed that are easy to regress:

- **Refusals must be readable.** The endpoint carries three rate limits, a body
  cap and field bounds (decision #43). `refusalMessage()` turns each status into
  something actionable, and reads `Retry-After` rather than guessing.
- **A question declined before any model was called** comes back with provider
  `"none"` and no citations. Do not print "every figure checked" over it — no
  check ran.

---

## 8. Future surfaces: what was decided and why

The brief asked for three possible homepage surfaces. The decisions:

**Live Anomaly Stream — built, and it is real.** Not a shell. `GET
/api/v1/anomalies` returns 25,413 detections with dates and Z-scores. The feed
keeps **one reading per series**: a month of policy decisions flags a dozen
countries at once and the same country's rate appearing three times is not three
facts. The heading says so, because a feed that quietly reshapes what it shows is
the small kind of lie this product cannot afford.

**A live tape — built, one only.** Under the topbar. Every item is a figure the
system currently holds or a real ingestion timestamp. 78 seconds per pass, pauses
on hover and on focus (a link that is moving is a link you cannot click), and
under reduced motion it becomes an ordinary scrollable strip rather than a frozen
marquee hiding half its contents.

**News — deliberately not built.** There is no news source, no connector, and
none in the Phase 5 list. A "coming soon" news rail on a product whose entire
claim is that it does not assert what it cannot verify would cost more than it
adds. **If it is wanted later, the honest version is a `/briefing` route** that
composes anomaly, ranking and forecast movements into a written digest — real
material the system already holds — rather than external headlines.

Where they live: both built surfaces are in `components/home/`. A News or
briefing surface would sit below the map section in `app/page.tsx`, in the same
measured column as the ranking rail and the feed.

---

## 9. Known gaps and tradeoffs

**`/status` does not exist and is linked from two places.** `docs/designsystem.md`
Flow 3 specifies a public status page; the backend already serves `GET /status`
with pipeline health, per-source ingestion timestamps and agent telemetry, and
`lib/api.ts` already has the `SystemStatus` type. The links in `TopBar` and
`SiteFooter` currently 404. The owner deferred it knowingly. **This is the first
thing to build.** `TopBar` already accepts `current="status"` for it.

**Bundle sizes.** `/` is 406 kB first load, `/country/[code]` 280 kB, `/chat`
172 kB. deck.gl and Recharts dominate; Motion, Radix, cmdk and Phosphor added
about 90 kB across the app. Nothing is lazy-loaded yet. If this needs to come
down, the map is the candidate — it is the only route that needs deck.gl.

**The chart draws with Recharts.** The design system reserves Recharts for
time-series and forbids it for the map; that boundary is intact.

**Four-turn history can pull a question toward the previous topic.** Asked for a
poem straight after a debt question, the agent tried to rank by "government debt
as a share of GDP". From a clean session the same question is declined correctly.
This is backend agent behaviour, not a frontend defect — do not "fix" it here.

**AI panels cost quota when cold.** `/vlm-interpret` generates on first view for a
country/series pair and caches for 7 days. Iterating visually on an uncached pair
spends real free-tier budget. Stick to a small set (`GHA`/`FP.CPI.TOTL.ZG` and
`JPN`/`GGXWDG_NGDP` are warm).

**The map's flagged markers do not pulse.** They could, but a permanent
`requestAnimationFrame` loop for ornament was not worth it; the sweep is already
that section's moment. The pulse lives in the anomaly feed, where there are few
elements and it is staggered so they never beat in unison.

**`country_profiles.flag_emoji` is unused.** A flag emoji is two
regional-indicator characters, and a platform without the glyph renders the
letters — on Windows the profile header read "GH Ghana" at 48px. The ISO-3 code
is used instead: always correct, and it is the identifier the rest of the product
already uses.

---

## 10. Before you touch anything

**Read `PROGRESS.md` and the relevant `docs/` files first.** They are untracked
and local-only, and they carry the decision log this document summarises.

**Run the gates.** `npm run build && npm test` (36 tests) and `npm run lint`. CI
runs backend `ruff check` **and** `ruff format --check` as separate steps, plus
the frontend lint, build and tests.

**CI builds without `NEXT_PUBLIC_API_URL`.** The env files are gitignored, so
every server-side fetch fails in CI and `fetchJson` returns `null`. Every page
must render an honest empty state under that condition — if you add a fetch, do
not assume it resolved. You can reproduce it by temporarily renaming
`.env.local` and `.env.production.local` and building.

**A passing build is not evidence a page works.** Every defect worth having found
in this redesign was found by opening the page: the tape making the document
4002px wide, the reveals shipping invisible, the map painting blank, the axis
floor, two search icons, a flag emoji rendering as letters. This project has the
scar tissue already — the Phase 2 map crash and the Markdown-in-the-panel bug
were both browser-only. **Open it.**

**Local development points at production.** `.env.local` holds
`NEXT_PUBLIC_API_URL=https://econradar-api.lalibela.store`, so `npm run dev`
serves real data. Read endpoints are free; the chat and VLM endpoints are not.

**Pushing to `main` deploys.** Vercel builds the frontend on every push. There is
no staging.

---

## 11. Where things are

```
frontend/
  app/
    layout.tsx            fonts, pointer provider, atmosphere, noscript reveal reset
    globals.css           the entire token system, keyframes, reduced-motion rules
    page.tsx              the map page (server)
    country/[code]/       the profile page (server)
    chat/                 the agent page (server shell)
    api/ai/[...path]/     server-side proxy to the AI endpoints, explicit allowlist
  components/
    ui/                   shadcn, vendored, ours to edit
    primitives.tsx        Panel, SectionHead, Figure, Meta, SourceMark, AnomalyBadge…
    atmosphere/           PointerField (one listener), Atmosphere (background)
    motion/               Reveal, Spotlight, Magnetic
    home/                 TopBar, LiveTape, RankingRail, AnomalyStream, SiteFooter,
                          IndicatorInstrument
    chat/                 Opening, Composer, Exchange
    WorldMap.tsx          deck.gl choropleth
    SeriesChart.tsx       Recharts time series + forecast
    ForecastChart.tsx     async forecast fetch + the summary row
    AiPanel.tsx           chart reading and flagged-point explanations
  lib/
    api.ts                every response type, fetch helpers, formatters
    series.ts             summary stats, series ordering (tested)
    chartScale.ts         axis domain and tick formatting (tested)
    colorScale.ts         choropleth ramps (tested)
    geo.ts                country anchors for the sweep and the markers
    motion.ts             durations, easings, variants
```

The proxy at `app/api/ai/[...path]/route.ts` deserves a note: it is an
**explicit allowlist**, not a prefix check. A catch-all segment concatenated onto
an upstream URL is an open proxy, and this one is reachable by anyone who can
load the site. If you add an AI endpoint, add it to `ALLOWED` deliberately.
