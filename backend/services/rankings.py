"""Global rankings and indicator metadata — the query surface the agent reasons over.

Two problems live here, and they are the same problem seen from two sides.

**A superlative is a claim about a dataset, not about a retrieval.** Asked which
country has the highest debt-to-GDP, a system that answers from whatever chunks a
vector search returned will name whichever country happened to be in them. That
is not a wrong retrieval — the fragment it quoted was real — it is a wrong *kind
of answer*, and no amount of better retrieval fixes it, because the question is
about all 194 countries and retrieval is definitionally a subset. So a superlative
has to be answered by a query that reads every country, every time.

**And a ranking is only meaningful if every country in it was measured the same
way.** This catalog holds two debt series: IMF general government (194 countries)
and World Bank central government (109). Ranking across a mix of the two would put
federal states artificially low and be wrong in a way that looks completely
plausible. So a ranking is always over one indicator, it always reports which one,
and it names the alternatives that measure the same concept differently.

`country_count` is reported even when `entries` is truncated, and `truncated` says
so outright. A caller asking for the top five is told it is seeing five of 194.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from logging_config import get_logger
from models import DataSource, IndicatorCatalog, TimeSeries
from schemas import IndicatorMetadataOut, RankingEntryOut, RankingOut

logger = get_logger(__name__)

#: A ranking never exceeds one row per country, so this bounds a response by the
#: shape of the data rather than by an arbitrary page size.
MAX_ENTRIES = 300


# ── naming ───────────────────────────────────────────────────────────────────
# The catalog's concepts are machine tokens — `government_debt`, `gdp_per_capita`.
# People, and models writing tool arguments on their behalf, type "public debt"
# and "gdp". Measured before this existed: of 29 phrasings a reader would
# plausibly use, **26 resolved to nothing**, including "government debt" — the
# concept's own name with a space instead of an underscore. Every one of those was
# a question the database could answer, answered with "EconRadar does not track
# anything matching that".
#
# Two rules, and the second is the more important one.


def _normalise(token: str) -> str:
    """`Debt-to-GDP ratio` and `debt to gdp ratio` are the same request."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", (token or "").lower())).strip("_")


#: Suffixes that name the *kind* of number rather than the subject, and so never
#: distinguish two things this catalog holds. Stripped only after a direct match
#: has already failed, so `exchange_rate` and `policy_rate` — concepts that end in
#: one of these words — are never mangled.
_TRAILING_QUALIFIERS: frozenset[str] = frozenset(
    {
        "rate",
        "rates",
        "ratio",
        "level",
        "levels",
        "index",
        "data",
        "figures",
        "statistics",
        "stats",
        "numbers",
        "percentage",
        "percent",
        "value",
        "values",
    }
)

#: Phrasings that mean exactly one concept.
CONCEPT_ALIASES: dict[str, str] = {
    # growth
    "economic_growth": "gdp_growth",
    "growth": "gdp_growth",
    "output_growth": "gdp_growth",
    "real_gdp_growth": "gdp_growth",
    "gdp_growth_rate": "gdp_growth",
    # income
    "gdp_per_head": "gdp_per_capita",
    "per_capita_gdp": "gdp_per_capita",
    "per_capita_income": "gdp_per_capita",
    "income_per_person": "gdp_per_capita",
    "income_per_capita": "gdp_per_capita",
    "average_income": "gdp_per_capita",
    "living_standards": "gdp_per_capita",
    # debt — this catalog holds no other kind, so "debt" is not ambiguous
    "debt": "government_debt",
    "public_debt": "government_debt",
    "national_debt": "government_debt",
    "sovereign_debt": "government_debt",
    "gross_debt": "government_debt",
    "debt_to_gdp": "government_debt",
    "debt_burden": "government_debt",
    "government_borrowing": "government_debt",
    # labour
    "jobless": "unemployment",
    "joblessness": "unemployment",
    "unemployed": "unemployment",
    "out_of_work": "unemployment",
    # prices
    "consumer_price_inflation": "inflation",
    "cpi_inflation": "inflation",
    "price_inflation": "inflation",
    "cost_of_living": "inflation",
    "consumer_price_index": "price_level",
    "consumer_prices": "price_level",
    "price_index": "price_level",
    "cpi_index": "price_level",
    # money
    "central_bank_rate": "policy_rate",
    "policy_interest_rate": "policy_rate",
    "monetary_policy_rate": "policy_rate",
    "benchmark_rate": "policy_rate",
    "base_rate": "policy_rate",
    "bank_rate": "policy_rate",
    "official_rate": "policy_rate",
    "government_bond_yield": "bond_yield",
    "bond_yields": "bond_yield",
    "sovereign_yield": "bond_yield",
    "long_term_interest_rate": "bond_yield",
    "ten_year_yield": "bond_yield",
    "10_year_yield": "bond_yield",
    "yield": "bond_yield",
    "fx": "exchange_rate",
    "fx_rate": "exchange_rate",
    "currency": "exchange_rate",
    "currency_rate": "exchange_rate",
    "dollar_exchange_rate": "exchange_rate",
    "usd_exchange_rate": "exchange_rate",
    # external
    "current_account_balance": "current_account",
    "external_balance": "current_account",
    "balance_of_payments": "current_account",
    "export": "exports",
    "import": "imports",
    # markets and industry
    "stock_market": "equity_market",
    "stock_market_index": "equity_market",
    "stock_prices": "equity_market",
    "share_prices": "equity_market",
    "equity_prices": "equity_market",
    "equities": "equity_market",
    "manufacturing_output": "industrial_production",
    "industrial_output": "industrial_production",
    "factory_output": "industrial_production",
}

#: Phrasings that mean more than one of the things this catalog holds. These are
#: **not** resolved to a best guess, and that is the point. Silently answering
#: "what is Japan's GDP?" with GDP *growth* is the metric-confusion failure the
#: whole indicator-metadata layer exists to prevent — it would be a real figure,
#: correctly sourced, and not the number the reader asked for. The caller is given
#: the candidates and asks again.
AMBIGUOUS_ALIASES: dict[str, tuple[str, ...]] = {
    "gdp": ("gdp_growth", "gdp_per_capita"),
    "gross_domestic_product": ("gdp_growth", "gdp_per_capita"),
    "economic_output": ("gdp_growth", "gdp_per_capita"),
    "economy_size": ("gdp_growth", "gdp_per_capita"),
    # "CPI" is the index; "CPI" is also what most people call CPI inflation. The
    # two differ by a whole transformation, so guessing is exactly wrong.
    "cpi": ("inflation", "price_level"),
    "prices": ("inflation", "price_level"),
    "price": ("inflation", "price_level"),
    # A policy rate and a 10-year yield are both "the interest rate".
    "interest_rate": ("policy_rate", "bond_yield"),
    "interest_rates": ("policy_rate", "bond_yield"),
    "borrowing_costs": ("policy_rate", "bond_yield"),
    # No net-trade series exists; exports and imports are separate, and the
    # current account is the closest single balance.
    "trade": ("exports", "imports", "current_account"),
    "trade_balance": ("exports", "imports", "current_account"),
}

#: Said out loud when a request names something the catalog cannot supply at all,
#: as opposed to something it names differently.
NOT_HELD: dict[str, str] = {
    "gdp": (
        "EconRadar holds no GDP *level* series — no total output in dollars. It "
        "holds GDP growth and GDP per capita."
    ),
    "gross_domestic_product": (
        "EconRadar holds no GDP *level* series — no total output in dollars. It "
        "holds GDP growth and GDP per capita."
    ),
    "trade_balance": (
        "EconRadar holds no net trade balance. It holds exports and imports "
        "separately, both as a share of GDP, and the current account balance."
    ),
}


@dataclass(frozen=True, slots=True)
class IndicatorResolution:
    """What a caller's indicator token turned out to mean.

    Three outcomes, and they are genuinely different: one series, several plausible
    series, or nothing. Collapsing the middle case into either of the others is how
    a request for "GDP" becomes an answer about growth.
    """

    token: str
    match: IndicatorMetadataOut | None = None
    candidates: list[IndicatorMetadataOut] = field(default_factory=list)
    note: str | None = None

    @property
    def ambiguous(self) -> bool:
        return self.match is None and bool(self.candidates)


async def list_indicator_metadata(
    session: AsyncSession,
    *,
    concept: str | None = None,
    indicator_code: str | None = None,
) -> list[IndicatorMetadataOut]:
    """Every ingested indicator with its full measurement metadata and coverage.

    Coverage is part of the metadata rather than a separate call because it is part
    of choosing: a 194-country series and a 109-country series measuring almost the
    same thing are not equally good answers to "which country has the most".
    """
    described = (
        IndicatorCatalog.indicator_code,
        IndicatorCatalog.indicator_name,
        IndicatorCatalog.category,
        IndicatorCatalog.unit,
        IndicatorCatalog.frequency,
        IndicatorCatalog.concept,
        IndicatorCatalog.metric_type,
        IndicatorCatalog.transformation,
        IndicatorCatalog.observation_basis,
        IndicatorCatalog.price_basis,
        IndicatorCatalog.coverage_definition,
        IndicatorCatalog.seasonal_adjustment,
        IndicatorCatalog.is_primary_for_concept,
        IndicatorCatalog.comparability_notes,
        DataSource.name.label("source"),
    )
    stmt = (
        select(
            *described,
            func.count(func.distinct(TimeSeries.country_code)).label("country_count"),
            func.count(TimeSeries.value).label("observation_count"),
            func.min(TimeSeries.date).label("earliest_date"),
            func.max(TimeSeries.date).label("latest_date"),
        )
        .join(DataSource, IndicatorCatalog.source_id == DataSource.id)
        .join(TimeSeries, TimeSeries.indicator_id == IndicatorCatalog.id)
        .group_by(*described)
    )
    if concept:
        stmt = stmt.where(IndicatorCatalog.concept == concept.strip().lower())
    if indicator_code:
        stmt = stmt.where(IndicatorCatalog.indicator_code == indicator_code.strip())

    rows = (await session.execute(stmt)).all()
    out = [
        IndicatorMetadataOut(
            indicator_code=r.indicator_code,
            indicator_name=r.indicator_name,
            source=r.source,
            unit=r.unit,
            frequency=r.frequency,
            category=r.category,
            concept=r.concept,
            metric_type=r.metric_type,
            transformation=r.transformation,
            observation_basis=r.observation_basis,
            price_basis=r.price_basis,
            coverage_definition=r.coverage_definition,
            seasonal_adjustment=r.seasonal_adjustment,
            is_primary_for_concept=bool(r.is_primary_for_concept),
            comparability_notes=r.comparability_notes,
            country_count=r.country_count,
            observation_count=r.observation_count,
            earliest_date=r.earliest_date,
            latest_date=r.latest_date,
        )
        for r in rows
    ]
    # Primary first, then widest coverage: the order a caller should consider them in.
    out.sort(key=lambda m: (not m.is_primary_for_concept, -m.country_count))
    return out


async def resolve_indicator_request(session: AsyncSession, token: str) -> IndicatorResolution:
    """Turn whatever a caller typed into a series, a choice of series, or nothing.

    Accepting a concept is not a convenience. A caller that has to guess an exact
    code guesses wrong, and the wrong guess here is not a 404 — it is a plausible
    ranking on the wrong measurement. Given "government_debt" this returns the
    series marked primary for that concept, which is a decision recorded in the
    database with its reasoning, rather than one improvised at question time.

    The order below is deliberate. An explicit code always wins, so a caller who
    knows exactly what it wants is never second-guessed. Concepts and aliases come
    next, and the trailing-qualifier strip comes last of all — running it earlier
    would turn `exchange_rate` into `exchange` and `policy_rate` into `policy`.
    """
    raw = (token or "").strip()
    if not raw:
        return IndicatorResolution(token=raw)

    exact = await list_indicator_metadata(session, indicator_code=raw)
    if exact:
        return IndicatorResolution(token=raw, match=exact[0])

    normalised = _normalise(raw)
    if not normalised:
        return IndicatorResolution(token=raw)

    for candidate in (normalised, _strip_qualifier(normalised)):
        if not candidate:
            continue
        resolution = await _resolve_normalised(session, raw, candidate)
        if resolution is not None:
            return resolution

    # Case-insensitive code match, last: codes are conventionally upper case, and
    # falling back to it before the concept lookup would shadow a concept name.
    folded = raw.casefold()
    for meta in await list_indicator_metadata(session):
        if meta.indicator_code.casefold() == folded:
            return IndicatorResolution(token=raw, match=meta)
    return IndicatorResolution(token=raw, note=NOT_HELD.get(normalised))


def _strip_qualifier(normalised: str) -> str:
    """`unemployment_rate` -> `unemployment`. One suffix, not repeatedly."""
    head, _, tail = normalised.rpartition("_")
    return head if head and tail in _TRAILING_QUALIFIERS else ""


async def _resolve_normalised(
    session: AsyncSession, raw: str, candidate: str
) -> IndicatorResolution | None:
    """One lookup pass over concepts and aliases. None means "keep looking"."""
    by_concept = await list_indicator_metadata(session, concept=candidate)
    if by_concept:
        # list_indicator_metadata sorts primary first.
        return IndicatorResolution(token=raw, match=by_concept[0])

    if (aliased := CONCEPT_ALIASES.get(candidate)) is not None:
        by_alias = await list_indicator_metadata(session, concept=aliased)
        if by_alias:
            logger.info("indicator alias: %r -> concept %r", raw, aliased)
            return IndicatorResolution(token=raw, match=by_alias[0])

    if (options := AMBIGUOUS_ALIASES.get(candidate)) is not None:
        found: list[IndicatorMetadataOut] = []
        for concept in options:
            primaries = await list_indicator_metadata(session, concept=concept)
            if primaries:
                found.append(primaries[0])
        if found:
            logger.info("indicator ambiguous: %r -> %s", raw, [m.indicator_code for m in found])
            return IndicatorResolution(token=raw, candidates=found, note=NOT_HELD.get(candidate))
    return None


async def resolve_indicator(session: AsyncSession, token: str) -> IndicatorMetadataOut | None:
    """The one unambiguous series a token names, or None.

    An ambiguous token returns None here — `rank_countries` must not pick between
    GDP growth and GDP per capita on a caller's behalf. Callers that can ask again
    use `resolve_indicator_request` and read `.candidates`.
    """
    return (await resolve_indicator_request(session, token)).match


async def rank_countries(
    session: AsyncSession,
    indicator_token: str,
    *,
    order: str = "desc",
    limit: int | None = None,
    max_age_years: int | None = None,
) -> RankingOut | None:
    """Every country ranked on one indicator by its most recent value.

    Reads `v_latest_observations`, which is the whole dataset by construction —
    there is no code path here that ranks a subset, because there is no parameter
    that would let a caller ask for one. `limit` truncates what is *returned* after
    the full ranking has been computed and counted.
    """
    meta = await resolve_indicator(session, indicator_token)
    if meta is None:
        return None

    direction = "asc" if str(order).lower() == "asc" else "desc"
    params: dict[str, object] = {"code": meta.indicator_code}
    cutoff_clause = ""
    if max_age_years is not None:
        params["cutoff"] = dt.date.today() - dt.timedelta(days=365 * max_age_years)
        cutoff_clause = " and observation_date >= :cutoff"

    rows = (
        await session.execute(
            text(
                "select country_code, country_name, region, value, observation_date, source "
                "from v_latest_observations "
                f"where indicator_code = :code{cutoff_clause} "
                f"order by value {direction}, country_code asc"
            ),
            params,
        )
    ).all()

    entries = [
        RankingEntryOut(
            rank=i,
            country_code=r.country_code,
            country_name=r.country_name,
            region=r.region,
            value=float(r.value),
            observation_date=r.observation_date,
            source=r.source,
        )
        for i, r in enumerate(rows, start=1)
    ]
    dates = [e.observation_date for e in entries]

    kept = entries if limit is None else entries[: max(1, min(limit, MAX_ENTRIES))]
    logger.info(
        "ranking: %s (%s) over %d countries, returning %d, order=%s",
        meta.indicator_code,
        meta.concept,
        len(entries),
        len(kept),
        direction,
    )
    return RankingOut(
        indicator=meta,
        order=direction,
        # The size of the ranking, not of the response. Reported alongside
        # `truncated` so a top-5 request cannot be mistaken for the whole world.
        country_count=len(entries),
        truncated=len(kept) < len(entries),
        earliest_observation=min(dates) if dates else None,
        latest_observation=max(dates) if dates else None,
        entries=kept,
        alternative_indicators=[
            alt
            for alt in await list_indicator_metadata(session, concept=meta.concept or "")
            if alt.indicator_code != meta.indicator_code
        ],
    )
