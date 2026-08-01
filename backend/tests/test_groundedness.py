"""Feature 1.5 — the groundedness verifier and the provider rotation.

These are the tests for CLAUDE.md's defining constraint: an LLM narrates
precomputed numbers and never generates one. The critical case is
`test_a_fabricated_number_is_caught`, and the critical *system* case is
`test_ungrounded_output_is_discarded_not_served` — catching a fabrication is only
worth anything if the response containing it never reaches a user.
"""

from __future__ import annotations

import pytest

from services import providers
from services.groundedness import extract_numbers, verify
from services.llm import LLMService, NarrationUnavailable
from services.providers import Completion, ProviderError, ProviderRateLimited

# The shape services/context.py produces, trimmed to what a verifier needs.
CONTEXT = {
    "country_code": "NGA",
    "country": "Nigeria",
    "region": "Sub-Saharan Africa",
    "indicator_code": "FP.CPI.TOTL.ZG",
    "indicator": "Inflation, consumer prices (annual %)",
    "unit": "%",
    "unit_suffix": "%",
    "frequency": "annual",
    "source": "world_bank",
    "observation_count": 44,
    "first_date": "1981-01-01",
    "last_date": "2024-01-01",
    "latest": {"date": "2024-01-01", "value": 33.2},
    "recent": [
        {"date": "2021-01-01", "value": 16.95},
        {"date": "2022-01-01", "value": 18.85},
        {"date": "2023-01-01", "value": 24.66},
        {"date": "2024-01-01", "value": 33.2},
    ],
    "extremes": {
        "min_value": 5.38,
        "min_date": "2006-01-01",
        "max_value": 72.84,
        "max_date": "1995-01-01",
    },
    "changes": {"change since the previous period (2023-01-01 to 2024-01-01)": "+8.54"},
    "anomalies": [
        {"date": "1995-01-01", "value": 72.84, "z_score": 3.4, "deviation_type": "spike"}
    ],
}


# ── number extraction ────────────────────────────────────────────────────────


def test_extractor_reads_figures_out_of_ordinary_prose():
    found = dict(extract_numbers("Inflation reached 33.2% in 2024, up from 24.66%."))
    assert found["33.2"] == 33.2
    assert found["2024"] == 2024.0
    assert found["24.66"] == 24.66


def test_extractor_handles_thousands_separators_and_currency():
    found = dict(extract_numbers("GDP per capita stood at $1,234.50."))
    assert found["1,234.50"] == 1234.5


def test_extractor_handles_negatives():
    assert dict(extract_numbers("The balance was -2.1% of GDP."))["-2.1"] == -2.1


# ── the core rule ────────────────────────────────────────────────────────────


def test_a_faithful_narration_is_grounded():
    text = (
        "Inflation in Nigeria reached 33.2% in 2024, extending a climb from 24.66% "
        "in 2023 — a change of +8.54. The 1995 spike to 72.84% remains the record high."
    )
    report = verify(text, CONTEXT)
    assert report.passed
    assert report.score == 1.0
    assert report.ungrounded == ()


def test_a_fabricated_number_is_caught():
    """The proof CLAUDE.md's hard rule is enforced and not merely asserted."""
    text = "Inflation in Nigeria reached 33.2% in 2024, after averaging 19.7% over the decade."
    report = verify(text, CONTEXT)

    assert not report.passed
    assert "19.7" in report.ungrounded
    assert "33.2" not in report.ungrounded  # the real figure is not blamed
    assert report.score < 1.0
    assert "19.7" in report.reason()


def test_a_number_the_model_computed_for_itself_is_caught():
    # 33.2 and 24.66 are both real; their difference was never supplied as 8.6.
    text = "Inflation rose 8.6 percentage points, from 24.66% to 33.2%."
    report = verify(text, CONTEXT)
    assert not report.passed
    assert "8.6" in report.ungrounded


def test_rounding_a_supplied_value_stays_grounded():
    # A narrator writing 24.7 for a stored 24.66 is being readable, not inventing.
    assert verify("Prices rose 24.7% in 2023.", CONTEXT).passed


def test_years_from_context_dates_are_grounded():
    assert verify("The series runs from 1981 to 2024.", CONTEXT).passed


def test_prose_with_no_figures_is_trivially_grounded():
    report = verify("Inflation continued to climb through the period.", CONTEXT)
    assert report.passed
    assert report.total_numbers == 0


def test_an_unsupported_ratio_word_still_fails():
    """features.md 1.5's "roughly a fifth vs 20%" case.

    A ratio word is a numeric claim carrying no digits. With nothing beside it to
    check it against, there is nothing to do but reject it.
    """
    report = verify("Inflation is roughly double what it was a few years ago.", CONTEXT)
    assert not report.passed
    assert "double" in report.approximations
    assert "approximation terms" in report.reason()


def test_a_ratio_word_is_cleared_when_both_figures_are_quoted(caplog):
    """Decision #41. 33.2 / 16.95 is 1.96, and "roughly double" is a fair reading of
    that — a summary of arithmetic the reader can do from the same sentence. This
    was rejected before, which is the over-strictness the owner reported."""
    report = verify("Inflation at 33.2% is roughly double the 16.95% seen in 2021.", CONTEXT)
    assert report.approximations == ()
    assert report.passed


def test_a_ratio_word_that_does_not_hold_is_still_rejected():
    # 33.2 is not ten times 24.66, and quoting both does not make it so.
    report = verify("Inflation at 33.2% is tenfold the 24.66% of 2023.", CONTEXT)
    assert "tenfold" in report.approximations
    assert not report.passed


def test_half_a_year_is_not_a_ratio():
    """ "the second half of 2024" is a period. Flagging the word alone failed
    otherwise-correct answers."""
    assert verify("Inflation reached 33.2% in the second half of 2024.", CONTEXT).passed


# ── arithmetic a reader can check (decision #41) ──────────────────────────────


def test_a_difference_between_two_quoted_figures_is_grounded():
    """The reported over-strictness, in its simplest form. 18.85 and 33.2 are both in
    the evidence; 14.35 is their difference, is not precomputed anywhere, and was
    being called a fabrication — retracting the whole answer over it.

    (The 2023→2024 move is *not* used here: `changes` already supplies +8.54, so it
    would pass on the old rule and prove nothing.)
    """
    report = verify(
        "Inflation rose from 18.85% in 2022 to 33.2% in 2024, a rise of 14.35 percentage points.",
        CONTEXT,
    )
    assert report.passed
    assert report.extra["derived"] == [pytest.approx(14.35)]


def test_arithmetic_that_is_simply_wrong_is_still_caught():
    """The property that makes the relaxation safe: the difference is recomputed,
    not taken on trust. Without this the rule would be "any number near two other
    numbers is fine"."""
    report = verify(
        "Inflation went from 18.85% in 2022 to 33.2% in 2024, a rise of 20.1 points.", CONTEXT
    )
    assert not report.passed
    assert "20.1" in report.ungrounded


def test_a_derivation_must_show_its_operands():
    """The operands have to be in the same sentence. "The average was 28.93%" may be
    true arithmetic on two figures elsewhere in the answer, but a reader cannot see
    that, and across a whole answer "some two numbers produce this" is barely a
    constraint at all."""
    report = verify("Inflation averaged 28.93% over the period.", CONTEXT)
    assert not report.passed
    assert "28.93" in report.ungrounded


def test_a_fabrication_beside_real_figures_is_not_rescued():
    """A long list of real numbers must not become cover for an invented one."""
    report = verify(
        "Inflation ran 16.95% in 2021, 18.85% in 2022, 24.66% in 2023 and 41.7% in 2025.",
        CONTEXT,
    )
    assert not report.passed
    assert "41.7" in report.ungrounded


def test_ordinary_counting_words_are_not_treated_as_claims():
    # "one of" must not trip the approximation check, or honest prose fails.
    assert verify("Nigeria is one of the economies tracked here.", CONTEXT).passed


def test_a_rescaled_value_is_grounded():
    context = {"gdp": 1_234_000_000_000}
    assert verify("GDP stood at 1.234 trillion.", context).passed


def test_the_threshold_is_configurable_not_hardcoded(monkeypatch):
    from config import settings

    report = verify("Inflation reached 33.2% after averaging 19.7%.", CONTEXT)
    assert not report.passed
    monkeypatch.setattr(settings, "groundedness_min_score", 0.4)
    assert report.passed  # same report, relaxed threshold


# ── the rotation ─────────────────────────────────────────────────────────────


@pytest.fixture
def all_keys(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "mistral_api_key", "test-mistral")
    monkeypatch.setattr(settings, "groq_api_key", "test-groq")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-openrouter")


def _completion(provider: str, text: str) -> Completion:
    return Completion(text=text, provider=provider, model=f"{provider}-model", token_count=42)


def test_the_provider_order_is_the_documented_one():
    assert LLMService.PROVIDER_ORDER == ("mistral", "groq", "openrouter")


def test_task_routing_starts_at_a_primary_but_keeps_openrouter_last():
    """Decision #24: routing chooses the entry point, not a new order."""
    service = LLMService()
    assert service.rotation_for("mistral") == ("mistral", "groq", "openrouter")
    assert service.rotation_for("groq") == ("groq", "mistral", "openrouter")
    assert service.rotation_for(None) == ("mistral", "groq", "openrouter")
    assert service.rotation_for("nonsense") == ("mistral", "groq", "openrouter")


async def test_rate_limit_falls_through_to_the_next_provider(monkeypatch, all_keys):
    seen: list[str] = []

    async def fake(provider, _messages, **_kw):
        seen.append(provider)
        if provider == "mistral":
            raise ProviderRateLimited("mistral rate limited (HTTP 429)")
        return _completion(provider, "Inflation reached 33.2% in 2024.")

    monkeypatch.setattr(providers, "complete_openai_compatible", fake)
    result = await LLMService().narrate([], context=CONTEXT)

    assert seen == ["mistral", "groq"]
    assert result.provider == "groq"
    assert "rate limited" in result.attempts[0]


async def test_ungrounded_output_is_discarded_not_served(monkeypatch, all_keys):
    """A fabrication must be impossible to serve, not merely scored."""

    async def fake(provider, _messages, **_kw):
        if provider == "mistral":
            return _completion(provider, "Inflation averaged 19.7% over the decade.")
        return _completion(provider, "Inflation reached 33.2% in 2024.")

    monkeypatch.setattr(providers, "complete_openai_compatible", fake)
    result = await LLMService().narrate([], context=CONTEXT)

    assert result.provider == "groq"
    assert "19.7" not in result.text
    assert "ungrounded" in result.attempts[0]
    assert result.groundedness.score == 1.0


async def test_all_providers_ungrounded_raises_rather_than_serving_anything(monkeypatch, all_keys):
    async def fake(provider, _messages, **_kw):
        return _completion(provider, "Inflation averaged 19.7% over the decade.")

    monkeypatch.setattr(providers, "complete_openai_compatible", fake)
    with pytest.raises(NarrationUnavailable, match="ungrounded"):
        await LLMService().narrate([], context=CONTEXT)


async def test_all_providers_rate_limited_raises(monkeypatch, all_keys):
    """features.md 1.5's "all three providers rate-limiting simultaneously" case."""

    async def fake(provider, _messages, **_kw):
        raise ProviderRateLimited(f"{provider} rate limited (HTTP 429)")

    monkeypatch.setattr(providers, "complete_openai_compatible", fake)
    with pytest.raises(NarrationUnavailable) as exc:
        await LLMService().narrate([], context=CONTEXT)
    for provider in LLMService.PROVIDER_ORDER:
        assert provider in str(exc.value)


async def test_no_configured_provider_is_a_clear_failure(monkeypatch):
    from config import settings

    for field in ("mistral_api_key", "groq_api_key", "openrouter_api_key"):
        monkeypatch.setattr(settings, field, None)
    with pytest.raises(NarrationUnavailable, match="no LLM provider is configured"):
        await LLMService().narrate([], context=CONTEXT)


async def test_an_unconfigured_provider_is_skipped_without_being_called(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "mistral_api_key", None)
    monkeypatch.setattr(settings, "groq_api_key", "test-groq")
    monkeypatch.setattr(settings, "openrouter_api_key", None)
    seen: list[str] = []

    async def fake(provider, _messages, **_kw):
        seen.append(provider)
        return _completion(provider, "Inflation reached 33.2% in 2024.")

    monkeypatch.setattr(providers, "complete_openai_compatible", fake)
    result = await LLMService().narrate([], context=CONTEXT)
    assert seen == ["groq"]
    assert result.provider == "groq"


async def test_a_broken_provider_falls_through_like_a_rate_limited_one(monkeypatch, all_keys):
    async def fake(provider, _messages, **_kw):
        if provider == "mistral":
            raise ProviderError("mistral HTTP 500: upstream error")
        return _completion(provider, "Inflation reached 33.2% in 2024.")

    monkeypatch.setattr(providers, "complete_openai_compatible", fake)
    assert (await LLMService().narrate([], context=CONTEXT)).provider == "groq"


# ── prompts ──────────────────────────────────────────────────────────────────


ANOMALY_PROMPT_CONTEXT = {
    "country": "Nigeria",
    "indicator": "Inflation, consumer prices (annual %)",
    "unit": "%",
    "unit_suffix": "%",
    "source": "world_bank",
    "anomaly": {"date": "1995-01-01", "value": 72.84, "z_score": 3.4, "deviation_type": "spike"},
    "window": [
        {"date": "1994-01-01", "value": 57.03},
        {"date": "1995-01-01", "value": 72.84},
        {"date": "1996-01-01", "value": 29.27},
    ],
    "other_anomalies": [{"date": "2024-01-01", "value": 33.2, "deviation_type": "spike"}],
}


def test_a_prompt_renders_every_supplied_number():
    from services import prompts

    rendered = prompts.render(
        "anomaly_explanation.j2", min_words=40, max_words=90, **ANOMALY_PROMPT_CONTEXT
    )
    for figure in ("72.84", "57.03", "29.27", "3.4", "33.2"):
        assert figure in rendered
    assert "Nigeria" in rendered


def test_a_prompt_missing_a_context_key_fails_loudly():
    """StrictUndefined: a silently truncated data block is the worst failure mode."""
    from jinja2 import UndefinedError

    from services import prompts

    with pytest.raises(UndefinedError):
        prompts.render("anomaly_explanation.j2", min_words=40, max_words=90)


def test_the_system_prompt_states_the_groundedness_rule():
    from services import prompts

    system = prompts.system_prompt().lower()
    assert "must appear in the data block" in system
    assert "do not calculate" in system
    assert "do not approximate" in system
