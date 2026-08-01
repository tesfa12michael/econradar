"""Global rankings and indicator metadata.

The failure these exist to prevent is not a crash. It is an answer that names
Montenegro as the world's most indebted country because Montenegro was in the
retrieved fragment — confident, sourced, and wrong about 193 other countries. So
the tests that matter here are about *what the response makes it possible to
claim*, not about whether the query returns rows.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from schemas import IndicatorMetadataOut, RankingEntryOut, RankingOut
from services import rankings

pytestmark = pytest.mark.usefixtures("override_session")

MIGRATION = pathlib.Path(__file__).resolve().parents[2] / (
    "supabase/migrations/0011_indicator_metadata.sql"
)


def _meta(code: str = "GGXWDG_NGDP", **over) -> IndicatorMetadataOut:
    base = {
        "indicator_code": code,
        "indicator_name": "General government gross debt (% of GDP)",
        "source": "imf",
        "unit": "%",
        "frequency": "annual",
        "concept": "government_debt",
        "metric_type": "percent_of_gdp",
        "transformation": "none",
        "observation_basis": "end_of_period",
        "price_basis": "nominal",
        "coverage_definition": "general_government",
        "seasonal_adjustment": "not_applicable",
        "is_primary_for_concept": True,
        "comparability_notes": "General government, not central government.",
        "country_count": 194,
    }
    return IndicatorMetadataOut(**{**base, **over})


def _ranking(entry_count: int, *, returned: int | None = None) -> RankingOut:
    entries = [
        RankingEntryOut(
            rank=i,
            country_code=f"C{i:02d}",
            country_name=f"Country {i}",
            value=300.0 - i,
            observation_date=dt.date(2026, 1, 1),
            source="imf",
        )
        for i in range(1, entry_count + 1)
    ]
    kept = entries if returned is None else entries[:returned]
    return RankingOut(
        indicator=_meta(),
        order="desc",
        country_count=len(entries),
        truncated=len(kept) < len(entries),
        earliest_observation=dt.date(2026, 1, 1),
        latest_observation=dt.date(2026, 1, 1),
        entries=kept,
    )


# ── the Montenegro guard ─────────────────────────────────────────────────────


def test_a_truncated_ranking_still_reports_the_whole_field(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking for five must not make the answer *about* five.

    `country_count` is the size of the ranking, never the size of the response, and
    `truncated` says so outright. Without both, a top-5 list is indistinguishable
    from a five-country dataset — which is exactly the mistake being fixed.
    """

    async def fake(_session, _token, **_kw):
        return _ranking(194, returned=5)

    monkeypatch.setattr(rankings, "rank_countries", fake)
    body = client.get("/api/v1/rankings/government_debt?limit=5").json()

    assert len(body["entries"]) == 5
    assert body["country_count"] == 194
    assert body["truncated"] is True


def test_an_untruncated_ranking_says_so(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(_session, _token, **_kw):
        return _ranking(194)

    monkeypatch.setattr(rankings, "rank_countries", fake)
    body = client.get("/api/v1/rankings/government_debt").json()
    assert body["truncated"] is False
    assert body["country_count"] == len(body["entries"]) == 194


def test_limit_cannot_be_used_to_widen_the_query() -> None:
    """`limit` trims a computed ranking; it is not a parameter of the ranking.

    There is deliberately no argument that narrows what gets ranked, so no caller —
    including a model writing its own tool arguments — can request a subset.
    """
    import inspect

    params = inspect.signature(rankings.rank_countries).parameters
    assert set(params) == {"session", "indicator_token", "order", "limit", "max_age_years"}


def test_every_entry_carries_its_own_observation_date() -> None:
    """Coverage differs by years across countries in the same ranking. A row without
    its date invites a reader to treat a 2019 reading as current."""
    for entry in _ranking(3).entries:
        assert entry.observation_date is not None


# ── choosing the right series ────────────────────────────────────────────────


async def test_a_concept_resolves_to_the_primary_series() -> None:
    """ "government_debt" must land on general government, not on whichever row the
    database returned first."""
    catalog = [
        _meta(
            "GC.DOD.TOTL.GD.ZS",
            coverage_definition="central_government",
            is_primary_for_concept=False,
            country_count=109,
        ),
        _meta("GGXWDG_NGDP", is_primary_for_concept=True, country_count=194),
    ]

    async def fake_list(_session, *, concept=None, indicator_code=None):
        if indicator_code:
            return [m for m in catalog if m.indicator_code == indicator_code]
        if concept:
            found = [m for m in catalog if m.concept == concept]
            found.sort(key=lambda m: (not m.is_primary_for_concept, -m.country_count))
            return found
        return catalog

    import services.rankings as mod

    original, mod.list_indicator_metadata = mod.list_indicator_metadata, fake_list
    try:
        resolved = await mod.resolve_indicator(None, "government_debt")
        assert resolved is not None
        assert resolved.indicator_code == "GGXWDG_NGDP"
        assert resolved.coverage_definition == "general_government"

        # An explicit code still wins over the concept default.
        explicit = await mod.resolve_indicator(None, "GC.DOD.TOTL.GD.ZS")
        assert explicit is not None
        assert explicit.coverage_definition == "central_government"

        assert await mod.resolve_indicator(None, "not_a_thing") is None
        assert await mod.resolve_indicator(None, "  ") is None
    finally:
        mod.list_indicator_metadata = original


def test_an_unknown_indicator_says_where_to_look(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A silent empty list would read as "no country has any debt"."""

    async def fake(_session, _token, **_kw):
        return None

    monkeypatch.setattr(rankings, "rank_countries", fake)
    resp = client.get("/api/v1/rankings/gdp_in_bananas")
    assert resp.status_code == 404
    assert "indicator-metadata" in resp.json()["detail"]


# ── the metadata itself ──────────────────────────────────────────────────────
# Read out of the migration rather than the database so CI stays hermetic. The
# database-backed half — "nothing ingested was left unclassified" — is marked
# `database` in test_schema_metadata.py.

VOCABULARIES = {
    "metric_type": {
        "percent_change",
        "percent_of_gdp",
        "percent_of_labor_force",
        "rate",
        "index",
        "currency_level",
        "currency_per_capita",
        "exchange_rate",
    },
    "transformation": {"none", "year_over_year", "month_over_month", "quarter_over_quarter"},
    "observation_basis": {"period_average", "end_of_period", "period_total", "point_in_time"},
    "price_basis": {"nominal", "real", "ppp", "not_applicable"},
    "coverage_definition": {
        "ilo_modelled",
        "national_definition",
        "oecd_harmonised",
        "general_government",
        "central_government",
        "not_applicable",
    },
    "seasonal_adjustment": {
        "seasonally_adjusted",
        "not_seasonally_adjusted",
        "not_applicable",
    },
}

#: Every row of the backfill VALUES list: source, code, concept, metric_type,
#: transformation, observation_basis, price_basis, coverage, seasonal, is_primary.
_ROW = re.compile(
    r"^\('(?P<source>[a-z_]+)', '(?P<code>[A-Z0-9._]+)', '(?P<concept>\w+)', '(?P<metric_type>\w+)', "
    r"'(?P<transformation>\w+)',\s*\n\s*'(?P<observation_basis>\w+)', '(?P<price_basis>\w+)', "
    r"'(?P<coverage_definition>\w+)', '(?P<seasonal_adjustment>\w+)', (?P<is_primary>true|false),",
    re.MULTILINE,
)


def _classified() -> list[dict[str, str]]:
    return [m.groupdict() for m in _ROW.finditer(MIGRATION.read_text(encoding="utf-8"))]


def test_every_ingested_indicator_is_classified() -> None:
    rows = _classified()
    assert len(rows) == 23, f"expected all 23 indicators classified, parsed {len(rows)}"
    assert len({(r["source"], r["code"]) for r in rows}) == 23, "duplicate (source, code)"


def test_metadata_values_stay_inside_the_declared_vocabularies() -> None:
    """The SQL CHECK constraints enforce this at write time; this catches a typo in
    the migration before it is ever applied."""
    for row in _classified():
        for column, allowed in VOCABULARIES.items():
            assert row[column] in allowed, f"{row['code']}.{column} = {row[column]!r}"


def test_exactly_one_primary_series_per_concept() -> None:
    """Two primaries would make "which country has the highest X" answerable two
    different ways, and the answers would differ."""
    primaries: dict[str, list[str]] = {}
    for row in _classified():
        if row["is_primary"] == "true":
            primaries.setdefault(row["concept"], []).append(row["code"])
    for concept, codes in primaries.items():
        assert len(codes) == 1, f"{concept} has {len(codes)} primaries: {codes}"

    concepts = {r["concept"] for r in _classified()}
    assert concepts == set(primaries), f"concepts with no primary: {concepts - set(primaries)}"


def test_the_two_debt_series_are_distinguishable() -> None:
    """The specific confusion that produced a wrong answer: general government and
    central government debt are both "debt (% of GDP)" and differ by tens of points
    for any federal state."""
    by_code = {r["code"]: r for r in _classified()}
    general, central = by_code["GGXWDG_NGDP"], by_code["GC.DOD.TOTL.GD.ZS"]
    assert general["concept"] == central["concept"] == "government_debt"
    assert general["coverage_definition"] == "general_government"
    assert central["coverage_definition"] == "central_government"
    assert general["is_primary"] == "true" and central["is_primary"] == "false"


def test_the_three_unemployment_series_are_distinguishable() -> None:
    """ILO-modelled, national definition and OECD-harmonised are three different
    numbers for the same country, and only one of them can be ranked globally."""
    by_code = {r["code"]: r for r in _classified()}
    coverage = {
        code: by_code[code]["coverage_definition"]
        for code in ("SL.UEM.TOTL.ZS", "LUR", "FRED.UNRATE")
    }
    assert coverage == {
        "SL.UEM.TOTL.ZS": "ilo_modelled",
        "LUR": "national_definition",
        "FRED.UNRATE": "oecd_harmonised",
    }
    # The globally comparable one is the default, because a ranking built on
    # national definitions is not a ranking.
    assert by_code["SL.UEM.TOTL.ZS"]["is_primary"] == "true"


def test_the_monthly_inflation_series_is_marked_year_over_year() -> None:
    """A monthly series carrying a year-on-year change is the single easiest thing
    to misread as month-on-month, and the error is roughly twelvefold."""
    monthly = {r["code"]: r for r in _classified()}["CPTOTSAXNZGY"]
    assert monthly["transformation"] == "year_over_year"
    assert monthly["metric_type"] == "percent_change"


def test_a_price_index_is_not_classified_as_a_rate() -> None:
    """FRED.CPI is a level with 1982-84 = 100. Treating it as inflation would report
    US inflation somewhere above 300%."""
    cpi = {r["code"]: r for r in _classified()}["FRED.CPI"]
    assert cpi["metric_type"] == "index"
    assert cpi["transformation"] == "none"
    assert cpi["concept"] == "price_level"
