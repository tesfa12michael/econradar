"""Features 2.1 and 2.3 — chart rendering, the VLM order, and explanation discipline.

The rendering tests are real: they draw actual PNGs and inspect the bytes. A mock
would prove nothing here, because the failure mode features.md 2.1 warns about is a
*silent* rendering failure — an empty canvas that a vision model then describes
with total confidence.
"""

from __future__ import annotations

import datetime as dt

import pytest

from services import providers
from services.chart_render import ChartRenderError, render_series_b64, render_series_png
from services.llm import NarrationUnavailable
from services.providers import Completion, ProviderError, ProviderRateLimited
from services.vlm import VLMService

HISTORY = [(dt.date(1980 + i, 1, 1), 10.0 + i * 1.5 + (i % 4)) for i in range(40)]
FORECAST = [(dt.date(2020 + i, 1, 1), 70.0 + i, 60.0 + i, 80.0 + i) for i in range(5)]
ANOMALIES = [(dt.date(2005, 1, 1), 47.5)]

CONTEXT = {
    "country": "Nigeria",
    "indicator": "Inflation, consumer prices (annual %)",
    "unit": "%",
    "latest": {"date": "2019-01-01", "value": 68.5},
    "extremes": {
        "min_value": 10.0,
        "min_date": "1980-01-01",
        "max_value": 68.5,
        "max_date": "2019-01-01",
    },
}

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# ── chart rendering (feature 2.1) ────────────────────────────────────────────


def test_a_chart_renders_to_a_real_png():
    payload = render_series_png(
        title="Nigeria — Inflation",
        unit="%",
        history=HISTORY,
        forecast=FORECAST,
        anomalies=ANOMALIES,
    )
    assert payload.startswith(PNG_MAGIC)
    assert len(payload) > 20_000  # a real plot, not an empty canvas


def test_a_chart_renders_without_a_forecast_or_anomalies():
    payload = render_series_png(title="Ghana — GDP growth", unit="%", history=HISTORY)
    assert payload.startswith(PNG_MAGIC)


def test_rendering_with_no_history_errors_loudly():
    """features.md 2.1: "silent image-rendering failures must error loudly"."""
    with pytest.raises(ChartRenderError, match="no historical observations"):
        render_series_png(title="Nowhere", unit="%", history=[])


def test_a_single_data_point_still_renders_rather_than_crashing():
    # features.md 2.1's "visually ambiguous chart" case: nothing to interpret is a
    # valid outcome, but it must not take the panel down on the way there.
    payload = render_series_png(title="One point", unit="%", history=[(dt.date(2024, 1, 1), 5.0)])
    assert payload.startswith(PNG_MAGIC)


def test_rendering_is_deterministic_for_identical_input():
    # Decision #9's actual substance — reproducible server-side rendering, as opposed
    # to a client screenshot that varies with browser and viewport.
    first = render_series_png(title="A", unit="%", history=HISTORY, forecast=FORECAST)
    second = render_series_png(title="A", unit="%", history=HISTORY, forecast=FORECAST)
    assert len(first) == len(second)


def test_the_base64_form_decodes_back_to_the_same_png():
    import base64

    encoded = render_series_b64(title="A", unit="%", history=HISTORY)
    assert base64.b64decode(encoded).startswith(PNG_MAGIC)


# ── the VLM provider order (feature 2.1) ─────────────────────────────────────


@pytest.fixture
def vlm_keys(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "google_agent_platform_api_key", "test-google")
    monkeypatch.setattr(settings, "qwen_api_key", "test-qwen")


def test_the_vlm_order_is_the_documented_one():
    assert VLMService.PROVIDER_ORDER == ("gemini_flash", "qwen3_vl_dashscope")


async def test_gemini_is_tried_first(monkeypatch, vlm_keys):
    async def fake_gemini(_prompt, *, image_b64=None, model=None):
        return Completion(
            text="The line climbs steadily to 68.5% by 2019.",
            provider="gemini_flash",
            model="gemini-3.6-flash",
        )

    monkeypatch.setattr(providers, "complete_gemini", fake_gemini)
    result = await VLMService().interpret("prompt", "aGk=", context=CONTEXT)
    assert result.provider == "gemini_flash"
    assert result.attempts == ()


async def test_gemini_rate_limited_falls_back_to_qwen(monkeypatch, vlm_keys):
    """features.md 2.1: "fallback triggers correctly on Gemini rate-limit"."""

    async def fake_gemini(_prompt, *, image_b64=None, model=None):
        raise ProviderRateLimited("gemini_flash rate limited (HTTP 429)")

    async def fake_qwen(_prompt, _image):
        return Completion(
            text="A steady climb, ending at 68.5%.",
            provider="qwen3_vl_dashscope",
            model="qwen3-vl-plus",
        )

    monkeypatch.setattr(providers, "complete_gemini", fake_gemini)
    monkeypatch.setattr(providers, "complete_vision_qwen", fake_qwen)

    result = await VLMService().interpret("prompt", "aGk=", context=CONTEXT)
    assert result.provider == "qwen3_vl_dashscope"
    assert "rate limited" in result.attempts[0]


async def test_a_vlm_reading_a_number_off_the_axes_is_discarded(monkeypatch, vlm_keys):
    """The failure mode that makes groundedness matter more for vision, not less.

    A model misreading a rendered axis label states the wrong figure with the
    confidence of something it saw. 54.3 is nowhere in the data block, so the
    reading is thrown away and the next provider tried.
    """

    async def fake_gemini(_prompt, *, image_b64=None, model=None):
        return Completion(
            text="The series peaks near 54.3% before easing.",
            provider="gemini_flash",
            model="gemini-3.6-flash",
        )

    async def fake_qwen(_prompt, _image):
        return Completion(
            text="The line rises steadily, ending at 68.5%.",
            provider="qwen3_vl_dashscope",
            model="qwen3-vl-plus",
        )

    monkeypatch.setattr(providers, "complete_gemini", fake_gemini)
    monkeypatch.setattr(providers, "complete_vision_qwen", fake_qwen)

    result = await VLMService().interpret("prompt", "aGk=", context=CONTEXT)
    assert result.provider == "qwen3_vl_dashscope"
    assert "54.3" not in result.text


async def test_both_vlm_providers_failing_raises(monkeypatch, vlm_keys):
    async def fake_gemini(_prompt, *, image_b64=None, model=None):
        raise ProviderError("gemini_flash returned no content (blocked: SAFETY)")

    async def fake_qwen(_prompt, _image):
        raise ProviderRateLimited("qwen rate limited")

    monkeypatch.setattr(providers, "complete_gemini", fake_gemini)
    monkeypatch.setattr(providers, "complete_vision_qwen", fake_qwen)

    with pytest.raises(NarrationUnavailable, match="every VLM provider failed"):
        await VLMService().interpret("prompt", "aGk=", context=CONTEXT)


async def test_no_vlm_key_is_a_clear_failure(monkeypatch):
    from config import settings

    # Both spellings must be cleared: settings.google_api_key falls back from one
    # to the other, so nulling only the new name would still find a real key in a
    # developer .env and quietly turn this test green for the wrong reason.
    monkeypatch.setattr(settings, "google_agent_platform_api_key", None)
    monkeypatch.setattr(settings, "google_ai_studio_api_key", None)
    monkeypatch.setattr(settings, "qwen_api_key", None)
    with pytest.raises(NarrationUnavailable, match="no VLM provider is configured"):
        await VLMService().interpret("prompt", "aGk=", context=CONTEXT)


# ── anomaly explanation prompt discipline (feature 2.3) ──────────────────────


def test_the_anomaly_prompt_forbids_naming_a_cause():
    """The fabrication the numeric verifier cannot see, so the prompt must block it.

    An invented driver — an election, a devaluation — contains no digits, so it
    would pass groundedness untouched. The instruction is the only control, which
    is why it is pinned here.
    """
    from services import prompts

    # Collapsed: the instruction wraps across lines in the template, and the model
    # reads prose, not lines.
    rendered = " ".join(
        prompts.render(
            "anomaly_explanation.j2",
            min_words=45,
            max_words=90,
            country="Nigeria",
            indicator="Inflation, consumer prices (annual %)",
            unit="%",
            unit_suffix="%",
            source="world_bank",
            anomaly={
                "date": "1995-01-01",
                "value": 72.84,
                "z_score": 3.4,
                "deviation_type": "spike",
            },
            window=[
                {"date": "1994-01-01", "value": 57.03},
                {"date": "1995-01-01", "value": 72.84},
            ],
            other_anomalies=[],
        )
        .lower()
        .split()
    )

    assert "do not name a cause" in rendered
    assert "the data does not say why" in rendered
    for forbidden in ("election", "war", "pandemic", "devaluation", "commodity shock"):
        assert forbidden in rendered  # named explicitly so the model cannot reach for them


def test_the_anomaly_prompt_distinguishes_nearby_anomalies():
    """features.md 2.3: "multiple close-together anomalies must be distinguished"."""
    from services import prompts

    rendered = prompts.render(
        "anomaly_explanation.j2",
        min_words=45,
        max_words=90,
        country="Nigeria",
        indicator="Inflation",
        unit="%",
        unit_suffix="%",
        source="world_bank",
        anomaly={"date": "1995-01-01", "value": 72.84, "z_score": 3.4, "deviation_type": "spike"},
        window=[{"date": "1995-01-01", "value": 72.84}],
        other_anomalies=[{"date": "1996-01-01", "value": 29.3, "deviation_type": "drop"}],
    )
    assert "do not merge them" in rendered.lower()
    assert "1996-01-01" in rendered


def test_a_structural_break_prompt_explains_the_missing_z_score():
    from services import prompts

    rendered = prompts.render(
        "anomaly_explanation.j2",
        min_words=45,
        max_words=90,
        country="Chile",
        indicator="Policy rate",
        unit="%",
        unit_suffix="%",
        source="bis",
        anomaly={
            "date": "2021-07-01",
            "value": 0.75,
            "z_score": None,
            "deviation_type": "structural_break",
        },
        window=[{"date": "2021-07-01", "value": 0.75}],
        other_anomalies=[],
    )
    # The statistic is undefined, not merely absent — the prompt must say which.
    assert "not defined for this observation" in rendered
