"""Checks that only the live database can make (`pytest -m database`).

The hermetic tests in `test_rankings.py` read the migration file, which proves the
migration is internally consistent and nothing more. It cannot see the case that
actually goes wrong in production: a connector ingests a *new* indicator, the
catalog row appears with NULL metadata, and every downstream answer about it
silently loses the ability to say what kind of number it is. There is no crash and
no error log — the field is simply absent, which is why it needs a test that
fails loudly rather than a convention nobody re-reads.

Deselected by default so CI stays hermetic. Run after any ingestion change:

    pytest -m database
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from db import normalize_db_url

pytestmark = [
    pytest.mark.database,
    pytest.mark.skipif(not settings.database_url, reason="DATABASE_URL is not configured"),
]

CLASSIFICATION_COLUMNS = (
    "concept",
    "metric_type",
    "transformation",
    "observation_basis",
    "price_basis",
    "coverage_definition",
    "seasonal_adjustment",
)


@pytest.fixture
async def session() -> AsyncSession:
    # normalize_db_url, not the raw setting: a plain postgresql:// URL resolves to
    # psycopg2 and fails to import, which reads as a missing dependency rather than
    # a configuration detail.
    engine = create_async_engine(normalize_db_url(settings.database_url or ""), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_no_ingested_indicator_is_left_unclassified(session: AsyncSession) -> None:
    """An indicator holding observations must say what it measures.

    Scoped to indicators that actually have data: a catalog row seeded ahead of its
    connector is not yet a problem, but one being served to readers is.
    """
    missing = (
        await session.execute(
            text(
                "select ic.indicator_code, "
                + ", ".join(f"ic.{c}" for c in CLASSIFICATION_COLUMNS)
                + " from indicators_catalog ic "
                "where exists (select 1 from time_series ts where ts.indicator_id = ic.id) "
                "and (" + " or ".join(f"ic.{c} is null" for c in CLASSIFICATION_COLUMNS) + ")"
            )
        )
    ).all()
    assert not missing, (
        "indicators with observations but no measurement metadata: "
        f"{[r.indicator_code for r in missing]}. Classify them in a migration — an "
        "unclassified indicator cannot be described unambiguously in an answer."
    )


async def test_every_concept_has_exactly_one_primary(session: AsyncSession) -> None:
    """Enforced by a partial unique index; asserted here so the failure names the
    concept rather than surfacing as a constraint violation on some later write."""
    rows = (
        await session.execute(
            text(
                "select concept, count(*) filter (where is_primary_for_concept) as primaries "
                "from indicators_catalog where concept is not null group by concept"
            )
        )
    ).all()
    assert rows, "no indicator carries a concept — migration 0011 has not been applied"
    for row in rows:
        assert row.primaries == 1, f"concept {row.concept!r} has {row.primaries} primary series"


async def test_the_views_exist_and_agree_with_the_table(session: AsyncSession) -> None:
    """v_observations must be the observations, not a subset that drifted.

    It excludes NULL values by design, so the count it reports has to equal the
    number of non-null rows in time_series exactly. A join written wrongly — an
    inner join to country_profiles, say — would silently drop every country with no
    profile row, and the only symptom would be a country missing from a ranking.
    """
    view_rows = (await session.execute(text("select count(*) from v_observations"))).scalar_one()
    table_rows = (
        await session.execute(text("select count(*) from time_series where value is not null"))
    ).scalar_one()
    assert view_rows == table_rows, (
        f"v_observations sees {view_rows} of {table_rows} non-null observations — "
        "a join in the view is dropping rows"
    )

    latest = (
        await session.execute(
            text(
                "select count(*) as rows, count(distinct indicator_code) as indicators "
                "from v_latest_observations"
            )
        )
    ).one()
    pairs = (
        await session.execute(
            text(
                "select count(*) from ("
                "  select distinct country_code, indicator_id from time_series "
                "  where value is not null"
                ") p"
            )
        )
    ).scalar_one()
    assert latest.rows == pairs, "v_latest_observations is not one row per (country, indicator)"


async def test_a_ranking_reaches_every_country_that_has_the_indicator(
    session: AsyncSession,
) -> None:
    """The Montenegro guard, against real data: the ranking's size must equal the
    number of countries holding that series, not the number retrieval found."""
    from services.rankings import rank_countries

    result = await rank_countries(session, "government_debt", limit=5)
    assert result is not None
    assert result.indicator.indicator_code == "GGXWDG_NGDP"
    assert result.indicator.coverage_definition == "general_government"

    expected = (
        await session.execute(
            text(
                "select count(distinct ts.country_code) from time_series ts "
                "join indicators_catalog ic on ic.id = ts.indicator_id "
                "where ic.indicator_code = 'GGXWDG_NGDP' and ts.value is not null"
            )
        )
    ).scalar_one()
    assert result.country_count == expected
    assert result.truncated is True and len(result.entries) == 5
    # And the alternative measurement is named rather than left implicit.
    assert [a.indicator_code for a in result.alternative_indicators] == ["GC.DOD.TOTL.GD.ZS"]
