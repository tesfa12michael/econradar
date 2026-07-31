"""Feature 2.2 — retrieval filters, conversation context, and the chat contract.

The chat tests drive `stream_chat` end to end with retrieval and caching stubbed,
because what needs proving is the *event contract*: that a refusal happens without
calling a model, that a failed verdict retracts and does not cache, and that a
provider dying mid-stream resets rather than splicing two half-answers together.
"""

from __future__ import annotations

import pytest

from services import chat as chat_module
from services.chat import stream_chat
from services.providers import ProviderRateLimited
from services.rag import INSUFFICIENT_DATA, Evidence, RetrievalResult, _names_country, trim_history


def _evidence(text: str, country: str = "NGA", similarity: float = 0.7) -> Evidence:
    return Evidence(
        chunk_text=text,
        chunk_type="data_snapshot",
        country_code=country,
        country_name="Nigeria",
        indicator_code="FP.CPI.TOTL.ZG",
        indicator_name="Inflation, consumer prices (annual %)",
        similarity=similarity,
    )


NIGERIA = _evidence(
    "Nigeria (NGA) — Inflation, consumer prices (annual %). Most recent value: 23.0% "
    "in 2025-01-01. Record covers 60 annual observations."
)


async def _collect(events) -> list[dict]:
    return [event async for event in events]


# ── country-name matching ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "question"),
    [
        ("ghana", "how does inflation in nigeria compare with ghana?"),  # trailing punctuation
        ("brazil", "what happened to brazilian policy rates?"),  # adjectival form
        ("ghana", "ghanaian inflation over time"),
        ("nigeria", "nigeria's inflation"),
        ("france", "tell me about france."),
    ],
)
def test_country_names_match_past_punctuation_and_adjectives(name, question):
    words = set(question.replace("?", " ").replace(".", " ").replace("'", " ").split())
    assert _names_country(name, question, words)


@pytest.mark.parametrize(
    ("name", "question"),
    [
        ("chile", "children are not an economic indicator"),  # prefix must be bounded
        ("ghana", "what is inflation?"),
        ("india", "indication of a slowdown"),
    ],
)
def test_unrelated_words_do_not_match_a_country(name, question):
    words = set(question.replace("?", " ").split())
    assert not _names_country(name, question, words)


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


# ── the chat contract ────────────────────────────────────────────────────────


@pytest.fixture
def stub_cache(monkeypatch):
    """No cache hit, and record whatever gets stored."""
    stored: list[dict] = []

    async def no_hit(*_args, **_kwargs):
        return None

    async def store(_session, **kwargs):
        stored.append(kwargs)

    monkeypatch.setattr(chat_module, "get_cached_response", no_hit)
    monkeypatch.setattr(chat_module, "store_response", store)
    return stored


@pytest.fixture
def keys(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "groq_api_key", "test-groq")
    monkeypatch.setattr(settings, "mistral_api_key", None)
    monkeypatch.setattr(settings, "openrouter_api_key", None)


def _stub_retrieval(monkeypatch, evidence: list[Evidence]):
    async def fake_retrieve(*_args, **_kwargs):
        return RetrievalResult(evidence=evidence, countries=["NGA"], indicators=[])

    monkeypatch.setattr(chat_module, "retrieve", fake_retrieve)


def _stub_stream(monkeypatch, chunks_by_provider: dict[str, list[str] | Exception]):
    def fake_stream(_self, _messages, *, provider="groq"):
        async def gen():
            outcome = chunks_by_provider.get(provider, [])
            if isinstance(outcome, Exception):
                raise outcome
            for chunk in outcome:
                yield chunk

        return gen()

    monkeypatch.setattr(chat_module.LLMService, "stream_answer", fake_stream)


async def test_no_relevant_evidence_refuses_without_calling_a_model(monkeypatch, stub_cache, keys):
    """The acceptance criterion: an insufficient-data fallback, not a fabrication."""
    _stub_retrieval(monkeypatch, [])

    def explode(*_args, **_kwargs):
        raise AssertionError("a model must not be called when nothing was retrieved")

    monkeypatch.setattr(chat_module.LLMService, "stream_answer", explode)

    events = await _collect(stream_chat(None, "write me a poem about databases"))
    kinds = [e["type"] for e in events]
    assert kinds == ["citations", "token", "verdict", "done"]
    assert events[1]["text"] == INSUFFICIENT_DATA
    assert events[2]["grounded"] is True
    assert stub_cache == []


async def test_a_grounded_answer_streams_then_verifies_and_caches(monkeypatch, stub_cache, keys):
    _stub_retrieval(monkeypatch, [NIGERIA])
    _stub_stream(monkeypatch, {"groq": ["Inflation in Nigeria ", "was 23.0% in 2025 [1]."]})

    events = await _collect(stream_chat(None, "what is nigerian inflation?"))
    tokens = [e["text"] for e in events if e["type"] == "token"]
    verdict = next(e for e in events if e["type"] == "verdict")

    assert "".join(tokens) == "Inflation in Nigeria was 23.0% in 2025 [1]."
    assert verdict["grounded"] is True
    assert verdict["provider"] == "groq"
    # Verdict is terminal and singular — the client depends on that.
    assert [e["type"] for e in events].count("verdict") == 1
    assert events[-1]["type"] == "done"
    assert len(stub_cache) == 1


async def test_a_fabricated_figure_is_retracted_and_never_cached(monkeypatch, stub_cache, keys):
    """Streaming shows text before it is verified, so retraction is the control.

    41.7% is nowhere in the retrieved evidence. The verdict must say so, and the
    answer must not be stored — otherwise the fabrication would be served again,
    instantly, from cache.
    """
    _stub_retrieval(monkeypatch, [NIGERIA])
    _stub_stream(monkeypatch, {"groq": ["Nigerian inflation averaged 41.7% over the decade [1]."]})

    events = await _collect(stream_chat(None, "what is nigerian inflation?"))
    verdict = next(e for e in events if e["type"] == "verdict")

    assert verdict["grounded"] is False
    assert "41.7" in verdict["reason"]
    assert stub_cache == []
    assert events[-1]["type"] == "done"


async def test_citations_are_emitted_before_any_token(monkeypatch, stub_cache, keys):
    # The UI renders source cards while the answer is still arriving.
    _stub_retrieval(monkeypatch, [NIGERIA])
    _stub_stream(monkeypatch, {"groq": ["Inflation was 23.0% [1]."]})

    events = await _collect(stream_chat(None, "nigeria inflation"))
    assert events[0]["type"] == "citations"
    assert events[0]["citations"][0]["index"] == 1
    assert events[0]["citations"][0]["country_code"] == "NGA"


async def test_a_provider_failing_mid_stream_resets_rather_than_splicing(
    monkeypatch, stub_cache, keys, request
):
    """Two providers must never contribute halves of one answer."""
    from config import settings

    monkeypatch.setattr(settings, "mistral_api_key", "test-mistral")
    _stub_retrieval(monkeypatch, [NIGERIA])

    def fake_stream(_self, _messages, *, provider="groq"):
        async def gen():
            if provider == "groq":
                yield "Inflation in Nigeria "
                raise ProviderRateLimited("groq rate limited (HTTP 429)")
            yield "Inflation in Nigeria was 23.0% in 2025 [1]."

        return gen()

    monkeypatch.setattr(chat_module.LLMService, "stream_answer", fake_stream)

    events = await _collect(stream_chat(None, "nigeria inflation"))
    kinds = [e["type"] for e in events]
    assert "reset" in kinds
    # Everything before the reset is discarded by the client; what remains is one
    # provider's complete answer.
    reset_at = kinds.index("reset")
    after = "".join(e["text"] for e in events[reset_at:] if e["type"] == "token")
    assert after == "Inflation in Nigeria was 23.0% in 2025 [1]."
    assert next(e for e in events if e["type"] == "verdict")["grounded"] is True


async def test_an_empty_question_is_rejected_immediately(stub_cache):
    events = await _collect(stream_chat(None, "   "))
    assert [e["type"] for e in events] == ["error", "done"]


async def test_a_cache_hit_skips_generation(monkeypatch, keys):
    from services.cache import CachedResponse

    _stub_retrieval(monkeypatch, [NIGERIA])

    async def hit(*_args, **_kwargs):
        return CachedResponse(
            text="Inflation in Nigeria was 23.0% in 2025 [1].",
            provider="groq",
            model="llama-3.3-70b-versatile",
            groundedness_score=1.0,
        )

    monkeypatch.setattr(chat_module, "get_cached_response", hit)

    def explode(*_args, **_kwargs):
        raise AssertionError("a cache hit must not call a provider")

    monkeypatch.setattr(chat_module.LLMService, "stream_answer", explode)

    events = await _collect(stream_chat(None, "nigeria inflation"))
    verdict = next(e for e in events if e["type"] == "verdict")
    assert verdict["cached"] is True
    assert verdict["grounded"] is True


async def test_the_collected_form_withholds_an_unverified_answer(monkeypatch, stub_cache, keys):
    _stub_retrieval(monkeypatch, [NIGERIA])
    _stub_stream(monkeypatch, {"groq": ["Nigerian inflation averaged 41.7% [1]."]})

    result = await chat_module.answer_chat(None, "nigeria inflation")
    assert result["answer"] == ""
    assert result["grounded"] is False
    assert result["error"]


# ── citation markers are markup, not numeric claims (feature 2.2) ─────────────


def test_citation_markers_are_separated_from_the_prose():
    prose, cited = chat_module.split_citation_markers(
        "Inflation was 23.0% [1] in 2025, above Ghana's 14.2% [12]."
    )
    assert cited == [1, 12]
    assert "[1]" not in prose and "[12]" not in prose
    assert "23.0%" in prose and "14.2%" in prose


async def test_a_citation_marker_is_not_scored_as_a_fabricated_number(
    monkeypatch, stub_cache, keys
):
    """The regression this pins was live, and failed answers for no real reason.

    `[4]` matches the verifier's number pattern exactly as a bare `4` does, so a
    correct answer was retracted because no figure in the evidence rounded to 4 —
    while `[6]` had passed elsewhere only because round(5.8, 0) == 6. Groundedness
    must not turn on the coincidence of a citation index.
    """
    _stub_retrieval(monkeypatch, [NIGERIA] * 8)
    _stub_stream(monkeypatch, {"groq": ["Inflation in Nigeria was 23.0% in 2025-01-01 [4]."]})

    events = await _collect(stream_chat(None, "nigeria inflation"))
    verdict = next(e for e in events if e["type"] == "verdict")
    assert verdict["grounded"] is True, verdict.get("reason")


async def test_a_citation_pointing_past_the_evidence_is_retracted(monkeypatch, stub_cache, keys):
    """The check the number pattern was never actually performing.

    One piece of evidence was retrieved, so [7] refers to nothing. That is a
    fabricated source, and a fabricated source is as serious as a fabricated
    figure — the answer is retracted rather than served with a dead marker.
    """
    _stub_retrieval(monkeypatch, [NIGERIA])
    _stub_stream(monkeypatch, {"groq": ["Inflation in Nigeria was 23.0% in 2025-01-01 [7]."]})

    events = await _collect(stream_chat(None, "nigeria inflation"))
    verdict = next(e for e in events if e["type"] == "verdict")
    assert verdict["grounded"] is False
    assert "[7]" in verdict["reason"]
