"""The trust battery — the answers this system must never give.

Every other test file asks whether a piece works. This one asks whether the whole
pipeline can be *made* to produce a specific wrong answer, and each case is drawn
from something that actually reached a reader or nearly did. The model is scripted
to behave badly on purpose; what is under test is the loop around it.

Read the docstrings as a list of the ways an economic chatbot lies:

* it names a winner from a fragment (Montenegro),
* it answers a word that means two things (GDP),
* it turns a gap in the record into a fact about the world (Gibraltar),
* it answers a question about the 1960s with last year's number,
* it invents arithmetic, or has honest arithmetic taken away from it,
* it says a rate fell when the evidence says it rose,
* and it compares two figures that were never measured the same way.

These run in CI with no network and no database. What they cover is *policy* — the
verifier, the guards, the tool contracts — because policy is what a live model
cannot be trusted to follow and what a regression would silently relax.
"""

from __future__ import annotations

import datetime as dt

import pytest

from schemas import IndicatorMetadataOut
from services import agent as agent_module
from services import agent_tools as tools_module
from services import chat as chat_module
from services import rankings
from services.agent import claims_a_global_superlative
from services.agent_tools import QUERY_OBSERVATIONS, RANK_COUNTRIES, ToolResult
from services.groundedness import verify

# ── fixtures shared by the battery ───────────────────────────────────────────


@pytest.fixture
def enabled(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "agent_enabled", True)
    monkeypatch.setattr(settings, "llm_enabled", True)


@pytest.fixture
def stub_cache(monkeypatch):
    """Nothing is read from or written to a real cache; the list is what was stored."""
    stored: list[dict] = []

    async def miss(_session, _key):
        return None

    async def store(_session, **kwargs):
        stored.append(kwargs)

    monkeypatch.setattr(chat_module, "get_cached_response", miss)
    monkeypatch.setattr(chat_module, "store_response", store)
    return stored


def _observations(**over) -> ToolResult:
    payload = {
        "country_code": "JPN",
        "country_name": "Japan",
        "indicator": {
            "indicator_code": "SL.UEM.TOTL.ZS",
            "indicator_name": "Unemployment, total (% of total labor force)",
            "source": "world_bank",
            "unit": "%",
            "metric_type": "percent_of_labor_force",
            "transformation": "none",
            "observation_basis": "period_average",
            "coverage_definition": "ilo_modelled",
            "comparability_notes": "Modelled ILO estimate.",
        },
        "series_coverage": {
            "observation_count": 35,
            "first_observation": "1991-01-01",
            "last_observation": "2025-01-01",
        },
        "observations": [{"date": "2025-01-01", "value": 2.5, "source": "world_bank"}],
    }
    payload.update(over)
    return ToolResult(
        name=QUERY_OBSERVATIONS,
        arguments={"country": "JPN", "indicator": "unemployment"},
        references=(("JPN", "SL.UEM.TOTL.ZS"),),
        payload=payload,
    )


def _ranking(country_count: int = 194) -> ToolResult:
    return ToolResult(
        name=RANK_COUNTRIES,
        arguments={"indicator": "government_debt"},
        references=(("VEN", "GGXWDG_NGDP"),),
        payload={
            "indicator": {
                "indicator_code": "GGXWDG_NGDP",
                "indicator_name": "General government gross debt (% of GDP)",
                "unit": "%",
                "coverage_definition": "general_government",
            },
            "country_count": country_count,
            "showing": 2,
            "rankings": [
                {
                    "rank": 1,
                    "country_code": "VEN",
                    "value": 308.7,
                    "observation_date": "2025-01-01",
                },
                {
                    "rank": 3,
                    "country_code": "JPN",
                    "value": 204.4,
                    "observation_date": "2026-01-01",
                },
            ],
        },
    )


def _stub_agent(monkeypatch, text: str, results: list[ToolResult], failure=None):
    from services.agent import AgentAnswer

    async def fake_run(_session, _question, _history=None):
        for result in results:
            yield "tool", result
        yield (
            "answer",
            AgentAnswer(
                text=text,
                provider="mistral_agent",
                model="stub",
                results=results,
                failure=failure,
            ),
        )

    monkeypatch.setattr(chat_module, "run_agent", fake_run)


async def _ask(monkeypatch, text: str, results: list[ToolResult], **kw) -> dict:
    _stub_agent(monkeypatch, text, results, **kw)
    return await chat_module.answer_chat(None, "a question")


def _catalog() -> list[IndicatorMetadataOut]:
    def meta(code, concept, name, primary=True, count=194):
        return IndicatorMetadataOut(
            indicator_code=code,
            indicator_name=name,
            source="world_bank",
            unit="%",
            concept=concept,
            is_primary_for_concept=primary,
            country_count=count,
        )

    return [
        meta("NY.GDP.MKTP.KD.ZG", "gdp_growth", "GDP growth (annual %)"),
        meta("NY.GDP.PCAP.CD", "gdp_per_capita", "GDP per capita (current US$)"),
        meta("FP.CPI.TOTL.ZG", "inflation", "Inflation, consumer prices (annual %)"),
        meta("FRED.CPI", "price_level", "Consumer Price Index"),
        meta("CBPOL", "policy_rate", "Central bank policy rate"),
        meta("FRED.GOV10Y", "bond_yield", "10-year government bond yield"),
        meta("SL.UEM.TOTL.ZS", "unemployment", "Unemployment (modeled ILO estimate)"),
        meta("GGXWDG_NGDP", "government_debt", "General government gross debt (% of GDP)"),
        meta("GC.DOD.TOTL.GD.ZS", "government_debt", "Central government debt", False, 109),
    ]


@pytest.fixture
def catalog(monkeypatch):
    entries = _catalog()

    async def fake_list(_session, *, concept=None, indicator_code=None):
        if indicator_code:
            return [m for m in entries if m.indicator_code == indicator_code]
        if concept:
            found = [m for m in entries if m.concept == concept]
            found.sort(key=lambda m: (not m.is_primary_for_concept, -m.country_count))
            return found
        return entries

    monkeypatch.setattr(rankings, "list_indicator_metadata", fake_list)


# ══ 1. Superlatives ═══════════════════════════════════════════════════════════
# The failure that started the rebuild: "which country has the highest
# debt-to-GDP" answered **Montenegro**, a real figure correctly quoted from a
# retrieved fragment and wrong about 193 other countries.


@pytest.mark.parametrize(
    "claim",
    [
        "Montenegro has the highest debt-to-GDP ratio in the world.",
        "No country worldwide carries more debt than Montenegro.",
        "Montenegro's ratio is the highest of all countries.",
        "Across all countries, Montenegro ranks highest.",
        "No other country has a higher ratio anywhere in the world.",
    ],
)
def test_a_worldwide_claim_is_recognised_however_it_is_phrased(claim: str) -> None:
    assert claims_a_global_superlative(claim), f"guard missed: {claim!r}"


@pytest.mark.parametrize(
    "sentence",
    [
        "That was Japan's highest unemployment reading since 1998.",
        "Japan's rate is lower than in the world's largest economies.",
        "Inflation peaked at its highest level in 2022.",
        "This is the most recent figure available for Japan.",
    ],
)
def test_an_honest_sentence_is_not_mistaken_for_a_worldwide_claim(sentence: str) -> None:
    """The half that matters more. A guard that rejects correct prose gets switched
    off, and then it protects nothing at all (decision #33's lesson)."""
    assert not claims_a_global_superlative(sentence)


async def test_a_superlative_without_a_ranking_never_reaches_a_reader(monkeypatch, one_provider):
    """The Montenegro answer, reproduced. A single-country lookup cannot support a
    claim about every country, whatever the model writes."""
    from services.providers import ToolCall, ToolCompletion

    steps = iter(
        [
            # It looks one country up — the retrieval-shaped move — and then makes a
            # claim about every country from it. That is the Montenegro answer.
            ToolCompletion(
                text="",
                tool_calls=(ToolCall(id="c1", name=QUERY_OBSERVATIONS, arguments={}),),
                provider="mistral_agent",
                model="stub",
            ),
            ToolCompletion(
                text="Montenegro has the highest debt-to-GDP ratio in the world, at 62.4% [1].",
                tool_calls=(),
                provider="mistral_agent",
                model="stub",
            ),
        ]
    )

    async def provider(_p, _s, _t, _tools):
        return next(steps)

    async def fake_execute(_session, _name, _args):
        return _observations()

    monkeypatch.setattr(agent_module.providers, "complete_with_tools", provider)
    monkeypatch.setattr(agent_module.agent_tools, "execute", fake_execute)

    answers = [
        item
        async for kind, item in agent_module.run_agent(None, "highest debt-to-GDP?")
        if kind == "answer"
    ]
    assert answers[0].text == ""
    assert "worldwide superlative" in answers[0].failure


async def test_a_ranking_answer_must_carry_the_size_of_the_field(
    monkeypatch, stub_cache, enabled
) -> None:
    """`country_count` is in the evidence, so an answer saying "194 countries" is
    grounded and one inventing "50 countries" is not. That is the difference between
    a ranking and a league table of whatever was convenient."""
    good = await _ask(
        monkeypatch,
        "Venezuela has the highest ratio at 308.7% in 2025, from a ranking of 194 countries [1].",
        [_ranking()],
    )
    assert good["grounded"] is True

    bad = await _ask(
        monkeypatch,
        "Venezuela has the highest ratio at 308.7%, from a ranking of 50 countries [1].",
        [_ranking()],
    )
    assert bad["grounded"] is False
    assert "50" in bad["error"]


# ══ 2. Ambiguous indicator names ══════════════════════════════════════════════
# "What is Japan's GDP?" is a question with no single answer here, and the wrong
# way to be helpful is to pick one.


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("gdp", {"NY.GDP.MKTP.KD.ZG", "NY.GDP.PCAP.CD"}),
        ("GDP", {"NY.GDP.MKTP.KD.ZG", "NY.GDP.PCAP.CD"}),
        ("gross domestic product", {"NY.GDP.MKTP.KD.ZG", "NY.GDP.PCAP.CD"}),
        ("cpi", {"FP.CPI.TOTL.ZG", "FRED.CPI"}),
        ("prices", {"FP.CPI.TOTL.ZG", "FRED.CPI"}),
        ("interest rate", {"CBPOL", "FRED.GOV10Y"}),
        ("interest rates", {"CBPOL", "FRED.GOV10Y"}),
    ],
)
async def test_an_ambiguous_word_is_never_resolved_to_a_guess(catalog, token, expected) -> None:
    resolution = await rankings.resolve_indicator_request(None, token)
    assert resolution.ambiguous, f"{token!r} was resolved to a single series"
    assert {m.indicator_code for m in resolution.candidates} == expected
    assert await rankings.resolve_indicator(None, token) is None


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("public debt", "GGXWDG_NGDP"),
        ("government debt", "GGXWDG_NGDP"),
        ("debt-to-GDP ratio", "GGXWDG_NGDP"),
        ("jobless rate", "SL.UEM.TOTL.ZS"),
        ("unemployment rate", "SL.UEM.TOTL.ZS"),
        ("inflation rate", "FP.CPI.TOTL.ZG"),
        ("cost of living", "FP.CPI.TOTL.ZG"),
        ("economic growth", "NY.GDP.MKTP.KD.ZG"),
        ("income per person", "NY.GDP.PCAP.CD"),
        ("central bank rate", "CBPOL"),
    ],
)
async def test_everyday_wording_still_resolves(catalog, token, expected) -> None:
    """The other side of the same coin. 26 of 29 phrasings resolved to nothing
    before decision #42, and every one was a question the database could answer."""
    resolved = await rankings.resolve_indicator(None, token)
    assert resolved is not None, f"{token!r} resolved to nothing"
    assert resolved.indicator_code == expected


async def test_a_concept_lands_on_the_series_meant_for_comparison(catalog) -> None:
    """Two debt series exist: IMF general government over 194 countries, and World
    Bank central government over 109. Ranking across a mix would put federal states
    artificially low and look completely plausible."""
    resolved = await rankings.resolve_indicator(None, "government_debt")
    assert resolved.indicator_code == "GGXWDG_NGDP"
    assert resolved.is_primary_for_concept


async def test_the_ambiguity_answer_offers_only_series_that_exist(monkeypatch) -> None:
    """Live, the agent answered "What is Japan's GDP?" by listing five GDP variants
    from memory — PPP, constant local currency — of which this database holds none.
    Whatever the reader is offered has to come out of the catalog."""
    growth = _catalog()[0]
    per_capita = _catalog()[1]

    async def fake_resolve(_session, token):
        return rankings.IndicatorResolution(
            token=token, candidates=[growth, per_capita], note="EconRadar holds no GDP level."
        )

    monkeypatch.setattr(tools_module, "resolve_indicator_request", fake_resolve)
    result = await tools_module.run_rank_countries(None, {"indicator": "gdp"})

    offered = {o["indicator_code"] for o in result.payload["options"]}
    assert offered == {"NY.GDP.MKTP.KD.ZG", "NY.GDP.PCAP.CD"}
    assert "PPP" not in str(result.payload)


# ══ 3. Missing in this dataset vs missing in reality ══════════════════════════


async def test_an_absent_country_is_a_fact_about_the_dataset(monkeypatch, stub_cache, enabled):
    """The reader must not be able to hear "the figure does not exist"."""
    absent = ToolResult(
        name=QUERY_OBSERVATIONS,
        arguments={"country": "GIB", "indicator": "inflation"},
        ok=False,
        reader_message=(
            "EconRadar holds no Inflation, consumer prices (annual %) for Gibraltar. "
            "The series covers 193 other countries — this is a gap in this dataset, "
            "not a statement about the country."
        ),
        payload={"error": "no observations", "countries_covered_by_this_series": 193},
    )
    result = await _ask(monkeypatch, "", [absent])

    assert result["grounded"] is True, "an honest absence is not a failure"
    assert "gap in this dataset" in result["answer"]
    assert "not a statement about the country" in result["answer"]


async def test_a_country_with_no_data_gets_no_figure(monkeypatch, stub_cache, enabled):
    """Every tool call failed, so there is no number the answer could legitimately
    contain — and the reader is told plainly rather than shown a retraction."""
    absent = ToolResult(
        name=QUERY_OBSERVATIONS,
        arguments={"country": "VGB", "indicator": "gdp_growth"},
        ok=False,
        reader_message="EconRadar holds no GDP growth for British Virgin Islands.",
        payload={"error": "no observations"},
    )
    result = await _ask(monkeypatch, "The British Virgin Islands grew 6.2% in 2025 [1].", [absent])

    assert result["grounded"] is True
    assert "6.2" not in result["answer"], "a model's invented figure must not survive"


def test_a_failed_lookup_grounds_nothing() -> None:
    """A failed call's payload is an error message. A model quoting a figure "from"
    it must not be grounded by the words in that message."""
    failed = ToolResult(
        name=QUERY_OBSERVATIONS,
        arguments={},
        ok=False,
        payload={"error": "No country matches 'Wakanda'."},
    )
    context = agent_module.evidence_context([failed])
    assert not verify("Wakanda's GDP grew 6.2% in 2025.", context).passed


# ══ 4. Date windows and coverage ══════════════════════════════════════════════


async def test_a_window_outside_the_record_is_reported_as_a_window(monkeypatch) -> None:
    """Japan's unemployment for 1960-1970 came back as "the dataset holds no
    observations of unemployment for Japan" — about a country this same tool answers
    correctly for 2025. The series starts in 1991."""

    class _Session:
        async def execute(self, *_a, **_k):
            class _R:
                def all(self_inner):
                    return []

                def one(self_inner):
                    return type("Row", (), {"n": 35, "first": "1991-01-01", "last": "2025-01-01"})()

            return _R()

    async def fake_country(_s, _t):
        return ("JPN", "Japan")

    async def fake_resolve(_s, token):
        return rankings.IndicatorResolution(token=token, match=_catalog()[6])

    monkeypatch.setattr(tools_module, "_resolve_country", fake_country)
    monkeypatch.setattr(tools_module, "resolve_indicator_request", fake_resolve)

    result = await tools_module.run_query_observations(
        _Session(),
        {"country": "JPN", "indicator": "unemployment", "start_date": "1960", "end_date": "1970"},
    )
    assert result.ok is True, "a series that exists must never be reported as absent"
    assert result.payload["observations"] == []
    assert "1991-01-01" in result.payload["no_data_in_requested_window"]
    assert "do NOT say the country has no data" in result.payload["no_data_in_requested_window"]


def test_a_date_window_is_never_silently_ignored() -> None:
    """`latest_only` defaults to true. A model supplying dates and leaving it alone
    was answering a different question from the one it asked, with nothing saying so."""
    assert tools_module._iso_date("1960") == dt.date(1960, 1, 1)
    assert tools_module._iso_date("1960-05") == dt.date(1960, 5, 1)
    assert tools_module._iso_date("1960-05-04") == dt.date(1960, 5, 4)
    assert tools_module._iso_date("the sixties") is None


async def test_a_stale_reading_keeps_its_own_date(monkeypatch, stub_cache, enabled) -> None:
    """Eritrea's most recent debt figure is from 2019 and legitimately outranks
    every 2026 reading below it. That is the correct answer to "latest value per
    country" — so the date travels with the row, and an answer that moves it is not
    grounded."""
    result = await _ask(
        monkeypatch,
        "Japan's ratio was 204.4% in 2026 and Venezuela's 308.7% in 2025 [1].",
        [_ranking()],
    )
    assert result["grounded"] is True

    # 2031 is *five years* from the 2026 in the evidence, which a 0.5% relative
    # band on a four-digit number used to accept. Years are now matched exactly.
    for invented in ("2031", "2045"):
        moved = await _ask(
            monkeypatch, f"Venezuela's ratio was 308.7% in {invented} [1].", [_ranking()]
        )
        assert moved["grounded"] is False, f"{invented} must not be grounded by 2026"

    # But naming the decade the evidence sits in is honest prose, and the first
    # draft of the year rule rejected it.
    decade = await _ask(
        monkeypatch,
        "Venezuela's ratio was 308.7% in 2025, the highest of the 2020s in this data [1].",
        [_ranking()],
    )
    assert decade["grounded"] is True


# ══ 5. Arithmetic ═════════════════════════════════════════════════════════════


def _two_countries() -> dict:
    return agent_module.evidence_context(
        [
            _observations(),
            ToolResult(
                name=QUERY_OBSERVATIONS,
                arguments={"country": "ZAF"},
                payload={
                    "country_code": "ZAF",
                    "indicator": {"indicator_code": "SL.UEM.TOTL.ZS", "unit": "%"},
                    "observations": [{"date": "2025-01-01", "value": 32.4}],
                },
            ),
        ]
    )


def test_a_difference_a_reader_can_check_is_allowed() -> None:
    """32.4 - 2.5 = 29.9, both figures quoted. Retracting this was the reported
    over-strictness (decision #41)."""
    report = verify(
        "South Africa's rate was 32.4% in 2025 while Japan's was 2.5%. The gap is 29.9 points.",
        _two_countries(),
    )
    assert report.passed


@pytest.mark.parametrize(
    "answer",
    [
        # asserted, not computed
        "South Africa's 32.4% against Japan's 2.5% is a gap of 4.4 percentage points.",
        # operands nowhere near it
        "The gap between them is 29.9 percentage points.",
        # a figure from nowhere at all
        "South Africa's rate was 32.4% and Nigeria's was 5.1%.",
    ],
)
def test_arithmetic_that_cannot_be_checked_is_rejected(answer: str) -> None:
    """The property that makes the relaxation safe rather than a hole: the
    verifier recomputes, it does not take the model's word."""
    assert not verify(answer, _two_countries()).passed


def test_a_ratio_word_is_checked_like_a_number() -> None:
    """ "Roughly double" is a numeric claim carrying no digits."""
    context = {"values": [33.2, 16.95], "dates": ["2021-01-01", "2024-01-01"]}
    assert verify("Inflation at 33.2% is roughly double the 16.95% of 2021.", context).passed
    assert not verify("Inflation at 33.2% is tenfold the 16.95% of 2021.", context).passed


# ══ 6. Directionality ═════════════════════════════════════════════════════════
# Decision #32: an answer can copy every figure perfectly and still be false.


def test_a_spike_described_as_a_drop_is_rejected() -> None:
    context = {
        "unit": "%",
        "anomalies": [{"date": "2002-10-01", "value": 21.0, "deviation_type": "spike"}],
    }
    assert not verify("The policy rate dropped to 21.0% in 2002-10-01.", context).passed
    assert verify("The policy rate rose to 21.0% in 2002-10-01.", context).passed


def test_a_level_presented_as_the_size_of_a_move_is_rejected() -> None:
    """70.8% is where Brazil's rate *landed*, having fallen from 15,406%. "A drop of
    70.8%" is the natural misreading and it is false by a factor of 200."""
    context = {
        "unit": "%",
        "anomalies": [{"date": "1994-07-01", "value": 70.8, "deviation_type": "drop"}],
    }
    assert not verify("There was a drop of 70.8% in 1994-07-01.", context).passed


def test_an_extreme_rate_must_carry_its_regime() -> None:
    """355,086% is a real stored value and a nominal annualised rate under a
    currency that no longer exists. Quoted bare, it invites comparison with today's
    15%."""
    context = {"unit": "%", "extremes": {"max_value": 355086.0}}
    assert not verify("Policy rates reached a high of 355086.0%.", context).passed
    assert verify(
        "Policy rates reached 355086.0%, a nominal annualised rate from a "
        "hyperinflation era that is not comparable with post-stabilisation levels.",
        context,
    ).passed


# ══ 7. Metric-type confusion ══════════════════════════════════════════════════
# The failure decision #36 exists to prevent: two real figures, correctly sourced,
# that were never measured the same way.


def test_every_figure_arrives_with_what_kind_of_number_it_is() -> None:
    """The tool contract. A row that omits its metric type cannot support an answer
    that states one, and an answer that states none is unusable."""
    block = _observations().payload["indicator"]
    for field in ("metric_type", "transformation", "observation_basis", "coverage_definition"):
        assert block.get(field), f"{field} missing from the evidence a model reads"


async def test_the_alternative_series_travel_with_a_ranking(monkeypatch) -> None:
    """A ranking names what it did *not* use, so an answer cannot quietly mix the
    194-country general-government series with the 109-country central-government
    one."""
    from schemas import RankingEntryOut, RankingOut

    primary = _catalog()[7]
    alternative = _catalog()[8]

    async def fake_rank(_s, _t, **_kw):
        return RankingOut(
            indicator=primary,
            order="desc",
            country_count=194,
            truncated=True,
            earliest_observation=dt.date(2019, 1, 1),
            latest_observation=dt.date(2026, 1, 1),
            entries=[
                RankingEntryOut(
                    rank=1,
                    country_code="VEN",
                    value=308.7,
                    observation_date=dt.date(2025, 1, 1),
                    source="imf",
                )
            ],
            alternative_indicators=[alternative],
        )

    async def fake_resolve(_s, token):
        return rankings.IndicatorResolution(token=token, match=primary)

    monkeypatch.setattr(tools_module, "rank_countries", fake_rank)
    monkeypatch.setattr(tools_module, "resolve_indicator_request", fake_resolve)

    result = await tools_module.run_rank_countries(None, {"indicator": "government_debt"})
    others = result.payload["other_series_measuring_the_same_concept"]
    assert [o["indicator_code"] for o in others] == ["GC.DOD.TOTL.GD.ZS"]
    assert "do not mix" in others[0]["why_not_used"]


def test_the_metadata_vocabularies_stay_closed() -> None:
    """A new value silently appearing in one of these columns would make two series
    look comparable when a CHECK constraint should have rejected them. Read out of
    the migration so CI needs no database."""
    import pathlib
    import re

    migration = (
        pathlib.Path(__file__).resolve().parents[2]
        / "supabase/migrations/0011_indicator_metadata.sql"
    ).read_text(encoding="utf-8")

    for column, expected in {
        "transformation": {"none", "year_over_year", "month_over_month", "quarter_over_quarter"},
        "price_basis": {"nominal", "real", "ppp", "not_applicable"},
    }.items():
        clause = re.search(
            rf"check\s*\(\s*{column}\s+is null\s+or\s+{column}\s+in\s*\(([^)]*)\)",
            migration,
            re.I | re.S,
        )
        assert clause, f"no CHECK constraint found for {column}"
        found = set(re.findall(r"'([a-z_]+)'", clause.group(1)))
        assert found == expected, f"{column} vocabulary drifted: {found ^ expected}"


# ══ 8. The structural guarantees ══════════════════════════════════════════════


def test_a_ranking_cannot_be_narrowed_by_any_caller() -> None:
    """There is deliberately no argument that filters *what gets ranked*, so no
    caller — including a model writing its own tool arguments — can request a
    subset and present it as the world."""
    import inspect

    params = set(inspect.signature(rankings.rank_countries).parameters)
    assert params == {"session", "indicator_token", "order", "limit", "max_age_years"}


def test_the_agent_has_exactly_two_tools() -> None:
    """The count is the design. Every additional tool is another route to an answer
    that has to be independently made safe, and there is deliberately no web search
    — a figure the database does not hold has no path into an answer."""
    names = {schema["function"]["name"] for schema in tools_module.TOOL_SCHEMAS}
    assert names == {QUERY_OBSERVATIONS, RANK_COUNTRIES}


async def test_an_answer_with_no_query_behind_it_is_refused(monkeypatch, one_provider) -> None:
    """Prose with no digits cannot fail a numeric verifier, so this is the one route
    parametric memory has left. Nothing but a structural check closes it."""
    from services.providers import ToolCompletion

    async def provider(_p, _s, _t, _tools):
        return ToolCompletion(
            text="GDP could mean nominal, PPP, or constant local currency.",
            tool_calls=(),
            provider="mistral_agent",
            model="stub",
        )

    monkeypatch.setattr(agent_module.providers, "complete_with_tools", provider)
    answers = [
        item
        async for kind, item in agent_module.run_agent(None, "What is Japan's GDP?")
        if kind == "answer"
    ]
    assert answers[0].text == ""
    assert "without querying the database" in answers[0].failure


@pytest.fixture
def one_provider(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "agent_provider_order", ("mistral_agent",))
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
