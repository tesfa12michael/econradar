"""The economic agent — tool loop, guardrails, and the chat event contract.

These replace `test_rag.py`. What is being proven changed with the mechanism: the
old tests asked whether retrieval found the right chunks, and these ask whether an
answer can be built from anything other than a tool result. That is the stronger
question, and it is the one the production failures were about.

The provider is stubbed throughout. What needs proving is not that Mistral can
call a function — it demonstrably can — but that the loop around it cannot be made
to produce an answer the data does not support.
"""

from __future__ import annotations

import json

import pytest

from services import agent as agent_module
from services import chat as chat_module
from services.agent import (
    asks_for_a_ranking,
    claims_a_global_superlative,
    evidence_context,
    trim_history,
)
from services.agent_tools import QUERY_OBSERVATIONS, RANK_COUNTRIES, ToolResult
from services.providers import AgentTurn, ToolCall, ToolCompletion


async def _collect(events) -> list[dict]:
    return [event async for event in events]


# ── the superlative guardrail ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question",
    [
        "Which country has the highest debt-to-GDP ratio?",
        "Which 5 countries have the lowest unemployment?",
        "Show me the top economies by GDP per capita",
        "Who has the worst current account balance?",
        "Rank countries by inflation",
    ],
)
def test_a_superlative_question_is_recognised(question):
    assert asks_for_a_ranking(question)


@pytest.mark.parametrize(
    "question",
    [
        "What is the most recent inflation figure for Japan?",
        "What is Nigeria's inflation rate?",
        "How has Brazil's policy rate moved since 1994?",
    ],
)
def test_an_ordinary_question_is_not_forced_into_a_ranking(question):
    """A false positive here costs a wasted tool call and drags an irrelevant
    league table into a single-country answer. "most recent" is the specific trap."""
    assert not asks_for_a_ranking(question)


def test_a_worldwide_claim_is_detected():
    assert claims_a_global_superlative("Montenegro has the highest debt-to-GDP in the world.")


def test_the_same_claim_phrased_as_a_negative_is_detected():
    """ "No country has a lower rate" is "this is the lowest" with different words,
    and a guard that only knew superlatives would wave it straight through."""
    assert claims_a_global_superlative("No country worldwide has a lower unemployment rate.")
    assert claims_a_global_superlative("No other country in the world carries more debt.")


def test_a_comparison_against_a_subset_is_not_a_global_claim():
    """ "The world's largest economies" describes a subset; it does not claim to be
    the largest. This sentence was rejected by the first draft of the guard, which
    is precisely the failure the guard exists to avoid being — so "the world's …"
    was dropped as a scope marker. The trade is deliberate: it misses "Venezuela has
    the world's highest debt", and the prompt plus the question-side directive
    remain responsible for that phrasing."""
    assert not claims_a_global_superlative(
        "Japan's rate is lower than in the world's largest economies."
    )


def test_a_within_series_superlative_is_left_alone():
    """The false positive that would matter most.

    "Japan's highest reading since 1998" is a claim about one series and is
    perfectly answerable from a single-country lookup. A guard that rejected it
    would suppress correct answers, which is worse than the failure it prevents —
    the same lesson decision #33 records about over-strict verification.
    """
    assert not claims_a_global_superlative(
        "That was Japan's highest unemployment reading since 1998."
    )
    assert not claims_a_global_superlative("Inflation peaked at its highest level in 2022.")


# ── conversation context ─────────────────────────────────────────────────────


def test_history_is_trimmed_to_the_documented_four_turns():
    history = [{"role": "user", "content": f"q{i}"} for i in range(20)]
    assert len(trim_history(history)) == 8  # four turns, two messages each


def test_history_keeps_the_most_recent_turns():
    history = [{"role": "user", "content": f"q{i}"} for i in range(10)]
    assert trim_history(history)[-1]["content"] == "q9"


def test_blank_turns_are_dropped():
    assert trim_history(
        [{"role": "user", "content": "   "}, {"role": "user", "content": "hi"}]
    ) == [{"role": "user", "content": "hi"}]


# ── verification context ─────────────────────────────────────────────────────


def _observation_result(value: float = 2.451) -> ToolResult:
    return ToolResult(
        name=QUERY_OBSERVATIONS,
        arguments={"country": "JPN", "indicator": "unemployment"},
        references=(("JPN", "SL.UEM.TOTL.ZS"),),
        payload={
            "country_code": "JPN",
            "country_name": "Japan",
            "indicator": {
                "indicator_code": "SL.UEM.TOTL.ZS",
                "indicator_name": "Unemployment, total (% of total labor force)",
                "source": "world_bank",
                "unit": "%",
                "metric_type": "percent_of_labor_force",
                "coverage_definition": "ilo_modelled",
                "comparability_notes": "Modelled ILO estimate.",
            },
            "observations": [{"date": "2025-01-01", "value": value, "source": "world_bank"}],
        },
    )


def test_the_verifier_context_is_exactly_what_the_tools_returned():
    """The property that makes groundedness mean something under an agent.

    The model saw these payloads and nothing else, so the numbers it may
    legitimately write are the numbers walked out of them — by construction, not by
    instruction.
    """
    from services.groundedness import verify

    context = evidence_context([_observation_result()])
    assert verify("Japan's unemployment rate was 2.5% in 2025.", context).passed
    assert not verify("Japan's unemployment rate was 7.8% in 2025.", context).passed


def test_a_failed_tool_call_grounds_nothing():
    """A failed lookup's payload is an error message. A model quoting a figure
    "from" it must not be grounded by the words in that message."""
    from services.groundedness import verify

    failed = ToolResult(
        name=QUERY_OBSERVATIONS,
        arguments={"country": "Wakanda", "indicator": "gdp_growth"},
        ok=False,
        reader_message="No country in the dataset matches 'Wakanda'.",
        payload={"error": "No country matches 'Wakanda'."},
    )
    assert not verify("Wakanda's GDP grew 6.2% in 2025.", evidence_context([failed])).passed


# ── the tool loop ────────────────────────────────────────────────────────────


class _ScriptedProvider:
    """Plays a fixed sequence of provider responses, recording what it was sent."""

    def __init__(self, *responses: ToolCompletion) -> None:
        self.responses = list(responses)
        self.seen: list[list[AgentTurn]] = []

    async def __call__(self, provider, system, turns, tools):
        self.seen.append(list(turns))
        return (
            self.responses.pop(0)
            if self.responses
            else ToolCompletion(text="done", tool_calls=(), provider=provider, model="stub")
        )


def _completion(text="", calls=()) -> ToolCompletion:
    return ToolCompletion(
        text=text, tool_calls=tuple(calls), provider="mistral_agent", model="stub"
    )


@pytest.fixture
def one_provider(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "agent_provider_order", ("mistral_agent",))
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")


async def test_the_loop_runs_a_tool_then_answers(monkeypatch, one_provider):
    scripted = _ScriptedProvider(
        _completion(
            calls=[ToolCall(id="c1", name=QUERY_OBSERVATIONS, arguments={"country": "JPN"})]
        ),
        _completion(text="Japan's unemployment rate was 2.5% in 2025 [1]."),
    )
    monkeypatch.setattr(agent_module.providers, "complete_with_tools", scripted)

    async def fake_execute(_session, _name, _args):
        return _observation_result()

    monkeypatch.setattr(agent_module.agent_tools, "execute", fake_execute)

    events = [item async for item in agent_module.run_agent(None, "japan unemployment")]
    kinds = [kind for kind, _ in events]
    assert kinds == ["tool", "answer"]
    answer = events[-1][1]
    assert "2.5%" in answer.text
    assert len(answer.results) == 1

    # The second model call must have seen the tool's output, or the loop is not a
    # loop — it is two independent questions.
    second_turns = scripted.seen[1]
    assert second_turns[-1].role == "tool"
    assert "2.451" in (second_turns[-1].text or "")


async def test_the_tool_budget_stops_a_model_that_never_converges(monkeypatch, one_provider):
    """A model that keeps calling tools has to be cut off by something other than
    goodwill — every extra turn is real quota against a public endpoint."""
    from config import settings

    monkeypatch.setattr(settings, "agent_max_tool_calls", 2)

    class _AlwaysCalls:
        calls = 0

        async def __call__(self, provider, system, turns, tools):
            _AlwaysCalls.calls += 1
            return _completion(
                calls=[ToolCall(id=f"c{_AlwaysCalls.calls}", name=QUERY_OBSERVATIONS, arguments={})]
            )

    monkeypatch.setattr(agent_module.providers, "complete_with_tools", _AlwaysCalls())

    async def fake_execute(_session, _name, _args):
        return _observation_result()

    monkeypatch.setattr(agent_module.agent_tools, "execute", fake_execute)

    events = [item async for item in agent_module.run_agent(None, "loop forever")]
    tool_events = [item for kind, item in events if kind == "tool"]
    assert len(tool_events) <= settings.agent_max_tool_calls


async def test_a_global_superlative_without_a_ranking_is_refused(monkeypatch, one_provider):
    """The Montenegro guard, as a veto rather than a hint.

    The model answers a worldwide superlative having only looked up one country.
    That is exactly the production failure, and the prompt asking it not to is not
    a control — this is.
    """
    scripted = _ScriptedProvider(
        _completion(calls=[ToolCall(id="c1", name=QUERY_OBSERVATIONS, arguments={})]),
        _completion(text="Montenegro has the highest debt-to-GDP ratio in the world."),
    )
    monkeypatch.setattr(agent_module.providers, "complete_with_tools", scripted)

    async def fake_execute(_session, _name, _args):
        return _observation_result()

    monkeypatch.setattr(agent_module.agent_tools, "execute", fake_execute)

    answer = [item for kind, item in [i async for i in agent_module.run_agent(None, "q")]][-1]
    assert answer.text == ""
    assert "without ranking every country" in (answer.failure or "")


async def test_the_same_claim_stands_when_the_ranking_was_actually_run(monkeypatch, one_provider):
    """The guard must not reject a superlative that *was* earned."""
    scripted = _ScriptedProvider(
        _completion(calls=[ToolCall(id="c1", name=RANK_COUNTRIES, arguments={})]),
        _completion(text="Venezuela has the highest debt-to-GDP ratio in the world."),
    )
    monkeypatch.setattr(agent_module.providers, "complete_with_tools", scripted)

    async def fake_execute(_session, _name, _args):
        return ToolResult(name=RANK_COUNTRIES, arguments={}, payload={"country_count": 194})

    monkeypatch.setattr(agent_module.agent_tools, "execute", fake_execute)

    answer = [item for kind, item in [i async for i in agent_module.run_agent(None, "q")]][-1]
    assert "Venezuela" in answer.text
    assert answer.failure is None


# ── the chat event contract ──────────────────────────────────────────────────


@pytest.fixture
def stub_cache(monkeypatch):
    stored: list[dict] = []

    async def no_hit(*_args, **_kwargs):
        return None

    async def store(_session, **kwargs):
        stored.append(kwargs)

    monkeypatch.setattr(chat_module, "get_cached_response", no_hit)
    monkeypatch.setattr(chat_module, "store_response", store)
    return stored


def _stub_agent(monkeypatch, answer_text: str, results: list[ToolResult], failure=None):
    from services.agent import AgentAnswer

    async def fake_run(_session, _question, _history=None):
        for result in results:
            yield "tool", result
        yield (
            "answer",
            AgentAnswer(
                text=answer_text,
                provider="mistral_agent",
                model="mistral-large-latest",
                results=results,
                failure=failure,
            ),
        )

    monkeypatch.setattr(chat_module, "run_agent", fake_run)


@pytest.fixture
def enabled(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "agent_enabled", True)
    monkeypatch.setattr(settings, "llm_enabled", True)


async def test_a_grounded_answer_emits_the_documented_event_order(monkeypatch, stub_cache, enabled):
    _stub_agent(
        monkeypatch, "Japan's unemployment rate was 2.5% in 2025 [1].", [_observation_result()]
    )
    events = await _collect(chat_module.stream_chat(None, "japan unemployment"))
    kinds = [e["type"] for e in events]

    assert kinds == ["tool", "citations", "token", "verdict", "done"]
    assert kinds.count("verdict") == 1  # terminal and singular — the client depends on it
    assert events[-1]["type"] == "done"
    assert next(e for e in events if e["type"] == "verdict")["grounded"] is True
    assert len(stub_cache) == 1


async def test_a_fabricated_figure_is_retracted_and_never_cached(monkeypatch, stub_cache, enabled):
    """41.7% is nowhere in the tool payload. The verdict must say so, and nothing
    may be stored — a cached fabrication would be served again instantly."""
    _stub_agent(monkeypatch, "Japan's unemployment averaged 41.7% [1].", [_observation_result()])
    events = await _collect(chat_module.stream_chat(None, "japan unemployment"))
    verdict = next(e for e in events if e["type"] == "verdict")

    assert verdict["grounded"] is False
    assert "41.7" in verdict["reason"]
    assert stub_cache == []


async def test_a_citation_pointing_past_the_evidence_is_retracted(monkeypatch, stub_cache, enabled):
    """A fabricated source is as serious as a fabricated figure (decision #30)."""
    _stub_agent(monkeypatch, "Unemployment was 2.5% in 2025 [7].", [_observation_result()])
    verdict = next(
        e for e in await _collect(chat_module.stream_chat(None, "q")) if e["type"] == "verdict"
    )
    assert verdict["grounded"] is False
    assert "[7]" in verdict["reason"]


async def test_a_citation_marker_is_not_scored_as_a_number(monkeypatch, stub_cache, enabled):
    """`[1]` matches the verifier's number pattern exactly as a bare 1 would."""
    _stub_agent(monkeypatch, "Unemployment was 2.5% in 2025-01-01 [1].", [_observation_result()])
    verdict = next(
        e for e in await _collect(chat_module.stream_chat(None, "q")) if e["type"] == "verdict"
    )
    assert verdict["grounded"] is True, verdict.get("reason")


async def test_every_tool_failing_answers_plainly_instead_of_retracting(
    monkeypatch, stub_cache, enabled
):
    """A country the database does not hold deserves a sentence, not a retraction.

    Found live: the first no-data question produced model prose the verifier then
    had to withdraw — a correct outcome presented to the reader as a failure.
    """
    absent = ToolResult(
        name=QUERY_OBSERVATIONS,
        arguments={"country": "Wakanda", "indicator": "gdp_growth"},
        ok=False,
        reader_message="No country in the dataset matches 'Wakanda'.",
        payload={"error": "No country matches 'Wakanda'. Use an ISO-3 code such as JPN."},
    )
    _stub_agent(monkeypatch, "Wakanda grew 6.2% last year.", [absent])
    events = await _collect(chat_module.stream_chat(None, "wakanda gdp"))
    text = next(e for e in events if e["type"] == "token")["text"]
    verdict = next(e for e in events if e["type"] == "verdict")

    assert "Wakanda" in text and "6.2" not in text
    # The model's prose never reaches the reader, and no internal instruction does
    # either — "Use an ISO-3 code" is written for the model, not for a person.
    assert "ISO-3" not in text
    assert verdict["grounded"] is True
    assert stub_cache == []


async def test_a_cache_hit_skips_the_model(monkeypatch, enabled):
    from services.cache import CachedResponse

    _stub_agent(monkeypatch, "unused", [_observation_result()])

    async def hit(*_args, **_kwargs):
        return CachedResponse(
            text="Japan's unemployment rate was 2.5% in 2025 [1].",
            provider="mistral_agent",
            model="mistral-large-latest",
            groundedness_score=1.0,
        )

    monkeypatch.setattr(chat_module, "get_cached_response", hit)
    verdict = next(
        e for e in await _collect(chat_module.stream_chat(None, "q")) if e["type"] == "verdict"
    )
    assert verdict["cached"] is True and verdict["grounded"] is True


async def test_an_empty_question_is_rejected_immediately():
    assert [e["type"] for e in await _collect(chat_module.stream_chat(None, "   "))] == [
        "error",
        "done",
    ]


async def test_the_collected_form_withholds_an_unverified_answer(monkeypatch, stub_cache, enabled):
    _stub_agent(monkeypatch, "Japan's unemployment averaged 41.7% [1].", [_observation_result()])
    result = await chat_module.answer_chat(None, "q")
    assert result["answer"] == ""
    assert result["grounded"] is False
    assert result["error"]
    # The tool trail is returned either way, so a caller can see what was consulted
    # even when the answer did not survive.
    assert result["tools"][0]["name"] == QUERY_OBSERVATIONS


async def test_a_recency_filter_that_excludes_everything_is_dropped(monkeypatch):
    """Too tight a window is not an absence of data, and saying so is false.

    Caught in a browser rather than by curl. Asked for the "current" highest
    unemployment rates, the model chose max_age_years=1; the World Bank's annual
    series is dated 2025-01-01, so a one-year window swept away all 187 countries
    and the tool reported "No ranking is available for 'unemployment'" — which a
    reader would take to mean the data does not exist.
    """
    import datetime as dt

    from schemas import IndicatorMetadataOut, RankingEntryOut, RankingOut
    from services import agent_tools as tools_module
    from services import rankings

    meta = IndicatorMetadataOut(
        indicator_code="SL.UEM.TOTL.ZS", indicator_name="Unemployment", source="world_bank"
    )
    full = RankingOut(
        indicator=meta,
        order="desc",
        country_count=187,
        truncated=False,
        earliest_observation=dt.date(2022, 1, 1),
        latest_observation=dt.date(2025, 1, 1),
        entries=[
            RankingEntryOut(
                rank=1,
                country_code="SWZ",
                value=34.2,
                observation_date=dt.date(2025, 1, 1),
                source="world_bank",
            )
        ],
    )

    async def fake_rank(_session, _token, *, order="desc", limit=None, max_age_years=None):
        # The window excludes everything; without it there are 187 countries.
        return None if max_age_years is not None else full

    async def fake_resolve(_session, token):
        return rankings.IndicatorResolution(token=token, match=meta)

    monkeypatch.setattr(tools_module, "rank_countries", fake_rank)
    monkeypatch.setattr(tools_module, "resolve_indicator_request", fake_resolve)
    result = await tools_module.run_rank_countries(
        None, {"indicator": "unemployment", "max_age_years": 1}
    )

    assert result.ok is True
    assert result.payload["country_count"] == 187
    # And the widening is reported, so the answer can say the readings are older.
    assert result.payload["recency_filter_dropped"]["requested_max_age_years"] == 1
    assert (
        result.payload["recency_filter_dropped"]["most_recent_observation_anywhere"] == "2025-01-01"
    )


# ── missing here vs missing everywhere (decision #42) ────────────────────────


class _FakeSession:
    """Answers the two `text()` queries `run_query_observations` runs, in order:
    the windowed row fetch, then the total coverage for the pair."""

    def __init__(self, rows: list, coverage: tuple[int, str | None, str | None]) -> None:
        self._rows, self._coverage, self._calls = rows, coverage, 0

    async def execute(self, *_args, **_kwargs):
        self._calls += 1
        session = self

        class _Result:
            def all(self_inner):
                return session._rows

            def one(self_inner):
                count, first, last = session._coverage
                return type("Row", (), {"n": count, "first": first, "last": last})()

        return _Result()


def _row(date: str, value: float):
    return type("Row", (), {"observation_date": date, "value": value, "source": "world_bank"})()


async def _query(monkeypatch, session, args) -> ToolResult:
    from schemas import IndicatorMetadataOut
    from services import agent_tools as tools_module
    from services import rankings

    meta = IndicatorMetadataOut(
        indicator_code="SL.UEM.TOTL.ZS",
        indicator_name="Unemployment, total (% of total labor force)",
        source="world_bank",
        country_count=187,
    )

    async def fake_country(_session, token):
        return ("JPN", "Japan") if token.upper() != "VGB" else ("VGB", "British Virgin Islands")

    async def fake_resolve(_session, token):
        return rankings.IndicatorResolution(token=token, match=meta)

    monkeypatch.setattr(tools_module, "_resolve_country", fake_country)
    monkeypatch.setattr(tools_module, "resolve_indicator_request", fake_resolve)
    return await tools_module.run_query_observations(session, args)


async def test_a_window_outside_the_record_is_not_an_absence_of_data(monkeypatch):
    """The reported failure, reproduced. Japan's unemployment from 1960 to 1970 came
    back as "the dataset holds no observations of unemployment for Japan" — about a
    country this same tool answers correctly for 2025. The window was outside the
    record; the record exists.
    """
    session = _FakeSession([], (35, "1991-01-01", "2025-01-01"))
    result = await _query(
        monkeypatch,
        session,
        {
            "country": "JPN",
            "indicator": "unemployment",
            "latest_only": False,
            "start_date": "1960-01-01",
            "end_date": "1970-01-01",
        },
    )

    assert result.ok is True, "a series that exists must not be reported as absent"
    assert result.payload["observations"] == []
    assert result.payload["series_coverage"] == {
        "observation_count": 35,
        "first_observation": "1991-01-01",
        "last_observation": "2025-01-01",
    }
    assert "1991-01-01" in result.payload["no_data_in_requested_window"]
    assert result.payload["requested_window"]["start_date"] == "1960-01-01"


async def test_a_country_the_dataset_omits_says_so_without_claiming_the_world(monkeypatch):
    """The other side of the same distinction. Nothing at all for this pair — said as
    a fact about EconRadar, with the series' coverage elsewhere alongside it, so
    neither the model nor a reader hears "this figure does not exist"."""
    session = _FakeSession([], (0, None, None))
    result = await _query(monkeypatch, session, {"country": "VGB", "indicator": "unemployment"})

    assert result.ok is False
    assert "EconRadar holds no" in result.reader_message
    assert "187 other countries" in result.reader_message
    assert result.payload["countries_covered_by_this_series"] == 187
    assert "not that the figure does not exist" in result.payload["error"]


async def test_rows_inside_the_window_still_answer_normally(monkeypatch):
    session = _FakeSession([_row("2025-01-01", 2.5)], (35, "1991-01-01", "2025-01-01"))
    result = await _query(monkeypatch, session, {"country": "JPN", "indicator": "unemployment"})

    assert result.ok is True
    assert result.payload["observations"] == [
        {"date": "2025-01-01", "value": 2.5, "source": "world_bank"}
    ]
    assert "no_data_in_requested_window" not in result.payload


async def test_a_value_is_rounded_before_the_model_sees_it(monkeypatch):
    """One object, two consumers. Told to "copy the digits exactly", Gemini reported
    Nigeria's inflation as 23.0101235833333% — precision the World Bank does not
    have. Rounding at the tool keeps the model and the verifier reading the same
    number, which is the rule narration has followed since decision #8."""
    session = _FakeSession([_row("2025-01-01", 23.0101235833333)], (44, "1981-01-01", "2025-01-01"))
    result = await _query(monkeypatch, session, {"country": "NGA", "indicator": "inflation"})
    assert result.payload["observations"][0]["value"] == 23.0


async def test_an_ambiguous_indicator_returns_the_choices_not_a_guess(monkeypatch):
    """A tool that picks for the model is a tool that decides what the question was."""
    from schemas import IndicatorMetadataOut
    from services import agent_tools as tools_module
    from services import rankings

    growth = IndicatorMetadataOut(
        indicator_code="NY.GDP.MKTP.KD.ZG", indicator_name="GDP growth (annual %)", source="wb"
    )
    per_capita = IndicatorMetadataOut(
        indicator_code="NY.GDP.PCAP.CD", indicator_name="GDP per capita (current US$)", source="wb"
    )

    async def fake_resolve(_session, token):
        return rankings.IndicatorResolution(
            token=token, candidates=[growth, per_capita], note="EconRadar holds no GDP level."
        )

    monkeypatch.setattr(tools_module, "resolve_indicator_request", fake_resolve)
    result = await tools_module.run_rank_countries(None, {"indicator": "gdp"})

    assert result.ok is False
    assert [o["indicator_code"] for o in result.payload["options"]] == [
        "NY.GDP.MKTP.KD.ZG",
        "NY.GDP.PCAP.CD",
    ]
    assert "ambiguous" in result.payload["error"]
    assert "Do not choose by guessing" in result.payload["error"]
    assert "GDP growth (annual %)" in result.reader_message


async def test_an_answer_with_no_query_behind_it_is_refused(monkeypatch, one_provider):
    """Problem 4 taking the last route open to it.

    Live, asked "What is Japan's GDP?", the agent skipped the tools and listed five
    GDP variants from memory — PPP, constant local currency, current US dollars — of
    which this database holds none. It scored 1.00, because prose with no digits in
    it cannot fail a numeric verifier. Nothing but a structural check catches that:
    no query, no answer.
    """
    provider = _ScriptedProvider(_completion(text="GDP could mean several things: PPP, nominal…"))
    monkeypatch.setattr(agent_module.providers, "complete_with_tools", provider)

    answers = [
        item
        async for kind, item in agent_module.run_agent(None, "What is Japan's GDP?", [])
        if kind == "answer"
    ]
    assert answers[0].text == ""
    assert "without querying the database" in answers[0].failure

    # It is asked once more before being refused — a refusal is a worse answer than
    # the one the tools would have given, and the usual cause is a model that
    # decided it already knew.
    assert len(provider.seen) == 2
    assert provider.seen[1][-1].text == agent_module.NO_QUERY_NUDGE


async def test_the_model_is_only_nudged_once(monkeypatch, one_provider):
    """A model that ignores the nudge is a model that cannot be told. Two rounds of
    this on a public endpoint with no rate limit is two model calls per question."""
    provider = _ScriptedProvider(
        _completion(text="GDP could mean several things"),
        _completion(text="I still think it could mean several things"),
    )
    monkeypatch.setattr(agent_module.providers, "complete_with_tools", provider)

    async for _ in agent_module.run_agent(None, "What is Japan's GDP?", []):
        pass
    assert len(provider.seen) == 2


def test_a_window_supplied_alongside_latest_only_is_honoured():
    """`latest_only` defaults to true, so a model that supplies dates and leaves it
    alone was answering a different question from the one it asked — silently."""
    from services import agent_tools as tools_module

    assert tools_module._iso_date("1960") == __import__("datetime").date(1960, 1, 1)
    assert tools_module._iso_date("1960-05") == __import__("datetime").date(1960, 5, 1)
    assert tools_module._iso_date("not a date") is None


def test_a_tool_call_from_another_provider_is_replayed_as_prose_for_gemini():
    """The handover this rotation exists to perform, which HTTP 400'd in production.

    Gemini 3.x rejects a `functionCall` part with no `thoughtSignature`, and a call
    Mistral made has none and never will. Replaying it as text keeps the evidence —
    byte-identical to what the verifier will check — instead of discarding a lookup
    that already ran.
    """
    from services.providers import _to_gemini_contents

    turns = [
        AgentTurn(role="user", text="What is Brazil's interest rate?"),
        AgentTurn(
            role="assistant",
            tool_calls=(ToolCall(id="c1", name=QUERY_OBSERVATIONS, arguments={"country": "BRA"}),),
        ),
        AgentTurn(
            role="tool", text='{"value": 15.0}', tool_call_id="c1", tool_name=QUERY_OBSERVATIONS
        ),
    ]
    contents = _to_gemini_contents(turns)

    parts = [part for content in contents for part in content["parts"]]
    assert all("functionCall" not in p for p in parts), "an unsigned call cannot be replayed as one"
    assert all("functionResponse" not in p for p in parts), "and neither can its response"
    # But the evidence itself survives, byte-identical to what the verifier checks.
    assert any('{"value": 15.0}' in p.get("text", "") for p in parts)


def test_a_signed_tool_call_still_goes_back_as_a_function_call():
    from services.providers import _to_gemini_contents

    turns = [
        AgentTurn(
            role="assistant",
            tool_calls=(ToolCall(id="c1", name=RANK_COUNTRIES, arguments={}, signature="sig-abc"),),
        ),
        AgentTurn(role="tool", text="{}", tool_call_id="c1", tool_name=RANK_COUNTRIES),
    ]
    contents = _to_gemini_contents(turns)
    assert contents[0]["parts"][0]["thoughtSignature"] == "sig-abc"
    assert contents[1]["parts"][0]["functionResponse"]["name"] == RANK_COUNTRIES


def test_citations_come_from_tool_results_not_similarity():
    citations = chat_module.citations_for([_observation_result()])
    assert len(citations) == 1
    assert citations[0].country_code == "JPN"
    assert citations[0].indicator_code == "SL.UEM.TOTL.ZS"
    assert citations[0].index == 1


# ── wire formats ─────────────────────────────────────────────────────────────


def test_mistral_content_parts_are_read_as_text():
    """Mistral returns `content` as a list of typed chunks once tool calling is in
    play. Reading `.strip()` off it is an AttributeError, not an empty answer —
    which is how it failed on the very first live run."""
    from services.providers import _content_text

    assert _content_text("plain") == "plain"
    assert (
        _content_text(
            [{"type": "text", "text": "Japan's rate "}, {"type": "text", "text": "is 2.5%."}]
        )
        == "Japan's rate is 2.5%."
    )
    # Reasoning parts are the scratchpad, not the answer: showing them to a reader
    # is bad, and feeding them to the verifier is worse.
    assert (
        _content_text([{"type": "thinking", "text": "maybe 9%?"}, {"type": "text", "text": "2.5%"}])
        == "2.5%"
    )


def test_a_tool_result_becomes_a_user_turn_for_gemini():
    """Google models a function response as something the caller hands back, so it
    carries the `user` role. Getting this wrong makes the model reissue the call."""
    from services.providers import _to_gemini_contents

    contents = _to_gemini_contents(
        [
            AgentTurn(role="user", text="japan unemployment"),
            AgentTurn(
                role="assistant",
                tool_calls=(
                    ToolCall(
                        id="g0",
                        name="query_observations",
                        arguments={"country": "JPN"},
                        signature="sig-abc",
                    ),
                ),
            ),
            AgentTurn(
                role="tool",
                text='{"value": 2.451}',
                tool_call_id="g0",
                tool_name="query_observations",
            ),
        ]
    )
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert "functionCall" in contents[1]["parts"][0]
    # Gemini 3.x rejects the next turn with HTTP 400 when the signature is missing.
    assert contents[1]["parts"][0]["thoughtSignature"] == "sig-abc"
    assert contents[2]["parts"][0]["functionResponse"]["name"] == "query_observations"
    # It must be an object, never a bare string.
    assert isinstance(contents[2]["parts"][0]["functionResponse"]["response"], dict)


def test_tool_calls_survive_the_openai_round_trip():
    from services.providers import _to_openai_messages

    messages = _to_openai_messages(
        "sys",
        [
            AgentTurn(role="user", text="q"),
            AgentTurn(
                role="assistant",
                tool_calls=(
                    ToolCall(id="c1", name="rank_countries", arguments={"indicator": "x"}),
                ),
            ),
            AgentTurn(role="tool", text="{}", tool_call_id="c1", tool_name="rank_countries"),
        ],
    )
    assert messages[0]["role"] == "system"
    call = messages[2]["tool_calls"][0]
    assert call["id"] == "c1"
    # Arguments go back as a JSON *string* in this dialect, not an object.
    assert json.loads(call["function"]["arguments"]) == {"indicator": "x"}
    assert messages[3]["tool_call_id"] == "c1"


def test_malformed_tool_arguments_degrade_instead_of_raising():
    """A model emitting broken JSON must reach the tool, which then says what it
    needed — a raise here would lose the whole question."""
    from services.providers import _decode_arguments

    assert _decode_arguments('{"country": "JPN"}') == {"country": "JPN"}
    assert _decode_arguments("{not json") == {}
    assert _decode_arguments(None) == {}
    assert _decode_arguments({"already": "object"}) == {"already": "object"}
