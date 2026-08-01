"""The agent's two tools — the only way it can learn a number.

There are exactly two, and the count is the design. Every additional tool is
another route to an answer that has to be independently made safe, and the two
here already cover the two shapes an economic question takes: *what is this
country's X* and *who has the most X*. There is no web search and no general
knowledge tool, so a figure the database does not hold has no path into an answer
at all — the model is not asked to resist the temptation, it is not given one.

**Every row carries its own context.** A tool never returns a bare number. It
returns the value, the date it was observed, who published it, what kind of
number it is, and what it must not be compared with — because the row is what the
verifier checks the answer against, and a row that omits its metric type cannot
support an answer that states one.

**Row caps are enforced here, after the model's argument.** `limit` is clamped to
`AGENT_MAX_ROWS` server-side, so a model that asks for fifty thousand rows gets
the cap and is told it was truncated. The truncation is reported in the payload
rather than applied silently — an agent that cannot see it was truncated will
describe a partial series as the whole one.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from logging_config import get_logger
from models import CountryProfile
from services.rankings import list_indicator_metadata, rank_countries, resolve_indicator

logger = get_logger(__name__)

QUERY_OBSERVATIONS = "query_observations"
RANK_COUNTRIES = "rank_countries"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What one tool call produced.

    `payload` goes to the model *and* into the groundedness context, which is the
    property that makes verification meaningful: the set of numbers the answer may
    contain is exactly the set the tools returned, by construction rather than by
    instruction.
    """

    name: str
    arguments: dict[str, Any]
    payload: dict[str, Any]
    #: (country_code, indicator_code) pairs this result touched — the citation cards.
    references: tuple[tuple[str | None, str | None], ...] = ()
    ok: bool = True
    #: What a *reader* should be told when this call found nothing, as opposed to
    #: `payload["error"]`, which is written for the model and carries instructions
    #: ("say this is not available rather than estimating it"). Keeping them apart
    #: matters: the first live no-data answer showed a user the prompt engineering.
    reader_message: str | None = None

    def summary(self) -> str:
        """A single line for the UI's progress events. Never the whole payload."""
        if not self.ok:
            return f"{self.name}: {self.payload.get('error', 'failed')}"
        if self.name == RANK_COUNTRIES:
            return (
                f"ranked {self.payload.get('country_count', 0)} countries on "
                f"{self.payload.get('indicator', {}).get('indicator_code', '?')}"
            )
        return (
            f"read {len(self.payload.get('observations', []))} observations for "
            f"{self.arguments.get('country', '?')} / {self.arguments.get('indicator', '?')}"
        )


# ── declarations ─────────────────────────────────────────────────────────────
# Written in the OpenAI shape and translated for Gemini in providers.py, so each
# tool is declared once. Two declarations of one tool are two things to keep in
# step, and they drift.

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": QUERY_OBSERVATIONS,
            "description": (
                "Read observations for one country and one indicator from the EconRadar "
                "database. Returns each value with its observation date, source, metric "
                "type, unit and comparability notes. Use this for any question about a "
                "specific country. It cannot rank countries against each other."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "country": {
                        "type": "string",
                        "description": "ISO-3 code (JPN) or country name (Japan).",
                    },
                    "indicator": {
                        "type": "string",
                        "description": (
                            "An indicator code (SL.UEM.TOTL.ZS) or a concept "
                            "(unemployment, inflation, government_debt, gdp_growth, "
                            "gdp_per_capita, current_account, exports, imports, "
                            "policy_rate, bond_yield, exchange_rate, price_level, "
                            "industrial_production, equity_market). A concept resolves "
                            "to the series best suited to cross-country comparison."
                        ),
                    },
                    "latest_only": {
                        "type": "boolean",
                        "description": "Only the most recent observation. Default true.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "ISO date; ignored when latest_only is true.",
                    },
                    "end_date": {"type": "string", "description": "ISO date."},
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"Maximum observations, capped at {settings.agent_max_rows}."
                        ),
                    },
                },
                "required": ["country", "indicator"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": RANK_COUNTRIES,
            "description": (
                "Rank EVERY country in the database by its most recent value for one "
                "indicator. This is the ONLY correct way to answer any question using "
                "the words highest, lowest, most, least, top, bottom, best, worst, "
                "ranked, or leading — those questions are about the whole dataset and "
                "cannot be answered from individual country lookups. The response "
                "always reports how many countries were ranked in total, even when the "
                "returned list is shorter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "indicator": {
                        "type": "string",
                        "description": "An indicator code or a concept, as above.",
                    },
                    "order": {
                        "type": "string",
                        "enum": ["desc", "asc"],
                        "description": "desc for highest first, asc for lowest first.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            "How many entries to return. The ranking is always computed "
                            "over every country regardless; this only trims the list."
                        ),
                    },
                    "max_age_years": {
                        "type": "integer",
                        "description": (
                            "Optionally exclude countries whose latest reading is older "
                            "than this many years. Use when the question says 'currently'."
                        ),
                    },
                },
                "required": ["indicator"],
            },
        },
    },
]


def _clamp(value: Any, default: int, ceiling: int) -> int:
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(wanted, ceiling))


def _iso_date(raw: Any) -> dt.date | None:
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


async def _resolve_country(session: AsyncSession, token: str) -> tuple[str, str | None] | None:
    """An ISO-3 code and name from a code or a name.

    Names are matched against `country_profiles` rather than a hard-coded list, so
    the resolver stays correct as coverage changes — and a miss returns None rather
    than the closest guess, because ranking the wrong country is worse than saying
    the country was not found.
    """
    token = (token or "").strip()
    if not token:
        return None
    upper = token.upper()
    if len(upper) == 3 and upper.isalpha():
        row = (
            await session.execute(
                select(CountryProfile.country_code, CountryProfile.country_name).where(
                    CountryProfile.country_code == upper
                )
            )
        ).first()
        if row:
            return row.country_code, row.country_name
        # An unknown three-letter code is still returned: the observation query will
        # come back empty, which is the honest answer, rather than "no such country".
        return upper, None

    folded = token.casefold()
    rows = (
        await session.execute(select(CountryProfile.country_code, CountryProfile.country_name))
    ).all()
    for row in rows:
        if (row.country_name or "").casefold() == folded:
            return row.country_code, row.country_name
    for row in rows:
        name = (row.country_name or "").casefold()
        # "Venezuela" for "Venezuela, RB"; "Korea" is deliberately NOT matched this
        # way in reverse, so a prefix only ever narrows.
        if name.startswith(folded) and len(folded) >= 4:
            return row.country_code, row.country_name
    return None


async def run_query_observations(session: AsyncSession, args: dict[str, Any]) -> ToolResult:
    """Observations for one (country, indicator), fully described."""
    country_token = str(args.get("country") or "")
    indicator_token = str(args.get("indicator") or "")

    resolved = await _resolve_country(session, country_token)
    if resolved is None:
        known = (
            (
                await session.execute(
                    select(CountryProfile.country_name)
                    .order_by(CountryProfile.country_name)
                    .limit(6)
                )
            )
            .scalars()
            .all()
        )
        return ToolResult(
            name=QUERY_OBSERVATIONS,
            arguments=args,
            ok=False,
            reader_message=f"No country in the dataset matches {country_token!r}.",
            payload={
                "error": (
                    f"No country matches {country_token!r}. Use an ISO-3 code such as JPN, "
                    f"or an exact name as the database spells it (for example: "
                    f"{', '.join(known)})."
                )
            },
        )
    country_code, country_name = resolved

    meta = await resolve_indicator(session, indicator_token)
    if meta is None:
        available = await list_indicator_metadata(session)
        return ToolResult(
            name=QUERY_OBSERVATIONS,
            arguments=args,
            ok=False,
            reader_message=f"EconRadar does not track anything matching {indicator_token!r}.",
            payload={
                "error": f"No indicator or concept matches {indicator_token!r}.",
                "available_concepts": sorted({m.concept for m in available if m.concept}),
            },
        )

    latest_only = args.get("latest_only", True)
    if isinstance(latest_only, str):
        latest_only = latest_only.strip().lower() not in {"false", "0", "no"}
    limit = _clamp(args.get("limit"), default=24, ceiling=settings.agent_max_rows)

    clauses = ["country_code = :country", "indicator_code = :code"]
    params: dict[str, Any] = {"country": country_code, "code": meta.indicator_code}
    if not latest_only:
        if (start := _iso_date(args.get("start_date"))) is not None:
            clauses.append("observation_date >= :start")
            params["start"] = start
        if (end := _iso_date(args.get("end_date"))) is not None:
            clauses.append("observation_date <= :end")
            params["end"] = end

    view = "v_latest_observations" if latest_only else "v_observations"
    # limit + 1: the extra row is how truncation is *detected* rather than assumed,
    # so `truncated` below is a fact about this result and not a guess.
    rows = (
        await session.execute(
            text(
                "select observation_date, value, source "
                f"from {view} where {' and '.join(clauses)} "
                "order by observation_date desc limit :lim"
            ),
            {**params, "lim": (1 if latest_only else limit + 1)},
        )
    ).all()

    truncated = not latest_only and len(rows) > limit
    rows = rows[:limit]

    if not rows:
        return ToolResult(
            name=QUERY_OBSERVATIONS,
            arguments=args,
            ok=False,
            reader_message=(
                f"The dataset holds no observations of {meta.indicator_name} for "
                f"{country_name or country_code}."
            ),
            payload={
                "error": (
                    f"The database holds no observations of "
                    f"{meta.indicator_name} for {country_name or country_code}. "
                    "Say this is not available rather than estimating it."
                ),
                "country": country_code,
                "indicator_code": meta.indicator_code,
            },
        )

    # Total coverage, always — so an answer built on a handful of rows cannot
    # describe the record as thin. This is the same failure decision #32 fixed for
    # the anomaly corpus, in a new place.
    coverage = (
        await session.execute(
            text(
                "select count(*) as n, min(observation_date) as first, "
                "max(observation_date) as last from v_observations "
                "where country_code = :country and indicator_code = :code"
            ),
            {"country": country_code, "code": meta.indicator_code},
        )
    ).one()

    logger.info(
        "tool %s: %s/%s -> %d rows (latest_only=%s)",
        QUERY_OBSERVATIONS,
        country_code,
        meta.indicator_code,
        len(rows),
        latest_only,
    )
    return ToolResult(
        name=QUERY_OBSERVATIONS,
        arguments=args,
        references=((country_code, meta.indicator_code),),
        payload={
            "country_code": country_code,
            "country_name": country_name,
            "indicator": _indicator_block(meta),
            "series_coverage": {
                "observation_count": coverage.n,
                "first_observation": str(coverage.first),
                "last_observation": str(coverage.last),
            },
            "truncated": truncated,
            "observations": [
                {
                    "date": str(r.observation_date),
                    "value": float(r.value),
                    "source": r.source,
                }
                for r in rows
            ],
        },
    )


def _indicator_block(meta: Any) -> dict[str, Any]:
    """The measurement description that travels with every figure."""
    return {
        "indicator_code": meta.indicator_code,
        "indicator_name": meta.indicator_name,
        "source": meta.source,
        "unit": meta.unit,
        "frequency": meta.frequency,
        "metric_type": meta.metric_type,
        "transformation": meta.transformation,
        "observation_basis": meta.observation_basis,
        "price_basis": meta.price_basis,
        "coverage_definition": meta.coverage_definition,
        "seasonal_adjustment": meta.seasonal_adjustment,
        "comparability_notes": meta.comparability_notes,
    }


async def run_rank_countries(session: AsyncSession, args: dict[str, Any]) -> ToolResult:
    """Every country ranked on one indicator (feature 2.8, decision #37)."""
    indicator_token = str(args.get("indicator") or "")
    order = str(args.get("order") or "desc").lower()
    order = "asc" if order == "asc" else "desc"
    limit = _clamp(args.get("limit"), default=10, ceiling=settings.agent_max_rows)
    max_age = args.get("max_age_years")
    max_age = (
        int(max_age) if isinstance(max_age, (int, float, str)) and str(max_age).isdigit() else None
    )

    result = await rank_countries(
        session, indicator_token, order=order, limit=limit, max_age_years=max_age
    )

    # A recency filter that excludes *everything* is a filter that was too tight,
    # not an absence of data — and reporting it as "no ranking is available" is
    # false. Found in a browser, not by curl: asked for the "current" highest
    # unemployment rates, the model chose max_age_years=1, and the World Bank's
    # annual series is dated 2025-01-01, so a one-year window swept away all 187
    # countries. The filter is dropped, the ranking is returned, and the payload
    # says the window was widened so the answer can say so too.
    dropped_filter: dict[str, Any] | None = None
    if max_age is not None and (result is None or not result.entries):
        unfiltered = await rank_countries(session, indicator_token, order=order, limit=limit)
        if unfiltered is not None and unfiltered.entries:
            dropped_filter = {
                "requested_max_age_years": max_age,
                "reason": (
                    "No country has an observation that recent. This series is not "
                    "updated that often; the ranking below uses each country's most "
                    "recent reading instead, and every entry carries its own date."
                ),
                "most_recent_observation_anywhere": str(unfiltered.latest_observation),
            }
            result = unfiltered

    if result is None or not result.entries:
        available = await list_indicator_metadata(session)
        return ToolResult(
            name=RANK_COUNTRIES,
            arguments=args,
            ok=False,
            reader_message=f"EconRadar cannot rank countries on {indicator_token!r}.",
            payload={
                "error": f"No ranking is available for {indicator_token!r}.",
                "available_concepts": sorted({m.concept for m in available if m.concept}),
            },
        )

    return ToolResult(
        name=RANK_COUNTRIES,
        arguments=args,
        references=tuple((e.country_code, result.indicator.indicator_code) for e in result.entries),
        payload={
            "indicator": _indicator_block(result.indicator),
            # The whole field, not the returned slice. An answer that says "highest in
            # the world" is a claim about this number.
            "country_count": result.country_count,
            "showing": len(result.entries),
            "truncated": result.truncated,
            "order": result.order,
            "observation_dates_span": {
                "earliest": str(result.earliest_observation),
                "latest": str(result.latest_observation),
            },
            **({"recency_filter_dropped": dropped_filter} if dropped_filter else {}),
            "rankings": [
                {
                    "rank": e.rank,
                    "country_code": e.country_code,
                    "country_name": e.country_name,
                    "value": e.value,
                    "observation_date": str(e.observation_date),
                    "source": e.source,
                }
                for e in result.entries
            ],
            "other_series_measuring_the_same_concept": [
                {
                    "indicator_code": alt.indicator_code,
                    "coverage_definition": alt.coverage_definition,
                    "country_count": alt.country_count,
                    "why_not_used": (
                        "different measurement basis — do not mix its values with these"
                    ),
                }
                for alt in result.alternative_indicators
            ],
        },
    )


async def execute(session: AsyncSession, name: str, args: dict[str, Any]) -> ToolResult:
    """Dispatch one tool call. An unknown name is a result, not an exception —
    the model can read the error and correct itself on the next turn."""
    if name == QUERY_OBSERVATIONS:
        return await run_query_observations(session, args)
    if name == RANK_COUNTRIES:
        return await run_rank_countries(session, args)
    return ToolResult(
        name=name,
        arguments=args,
        ok=False,
        reader_message="The agent tried an action that does not exist.",
        payload={
            "error": f"There is no tool called {name!r}. "
            f"The available tools are {QUERY_OBSERVATIONS} and {RANK_COUNTRIES}."
        },
    )
