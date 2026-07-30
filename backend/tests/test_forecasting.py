"""Feature 1.4 — the forecasting cascade, its guards, and its date arithmetic.

The cascade tests inject failures rather than mocking the whole service, because
the acceptance criterion is specifically that "the cascade falls back correctly when
a higher-priority model errors or times out" — which is a claim about the control
flow between backends, not about any one of them.
"""

from __future__ import annotations

import datetime as dt
import math

import pytest

from services import forecasting
from services.forecast_store import advance, forecast_cache_key
from services.forecasting import (
    ForecastingService,
    ForecastRejected,
    ForecastResult,
    ForecastUnavailable,
    _check_plausible,
    _from_modal,
    horizon_for,
    seasonality_for,
)
from services.modal_client import ModalUnavailable

# A rising series with a repeating wobble — long enough to clear the minimum and
# regular enough that any working model produces something near its continuation.
RISING = [100.0 + 2.0 * i + (i % 3) for i in range(60)]


def _payload(model: str, horizon: int = 5) -> dict:
    return {
        "model": model,
        "median": [200.0] * horizon,
        "lower": [190.0] * horizon,
        "upper": [210.0] * horizon,
    }


# ── frequency-derived settings ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("frequency", "season"),
    [("monthly", 12), ("quarterly", 4), ("annual", 1), ("Monthly", 12), (None, 1), ("", 1)],
)
def test_seasonality_comes_from_the_declared_frequency(frequency, season):
    # Decision #18 put frequency in the catalog precisely so this is not guessed.
    assert seasonality_for(frequency) == season


def test_horizon_is_periods_of_the_series_own_frequency():
    # A literal "12 months" would be one step for an annual series, which is not a
    # forecast; the horizon is therefore set per frequency.
    assert horizon_for("monthly") == 12
    assert horizon_for("quarterly") == 8
    assert horizon_for("annual") == 5
    assert horizon_for(None) == 5


# ── forecast date arithmetic ─────────────────────────────────────────────────


def test_advance_steps_annual_series_by_years():
    assert advance(dt.date(2025, 1, 1), "annual", 1) == dt.date(2026, 1, 1)
    assert advance(dt.date(2025, 1, 1), "annual", 5) == dt.date(2030, 1, 1)


def test_advance_rolls_monthly_series_over_the_year_boundary():
    assert advance(dt.date(2026, 11, 1), "monthly", 1) == dt.date(2026, 12, 1)
    assert advance(dt.date(2026, 11, 1), "monthly", 2) == dt.date(2027, 1, 1)
    assert advance(dt.date(2026, 12, 1), "monthly", 12) == dt.date(2027, 12, 1)


def test_advance_steps_quarterly_series_by_three_months():
    assert advance(dt.date(2026, 10, 1), "quarterly", 1) == dt.date(2027, 1, 1)
    assert advance(dt.date(2026, 1, 1), "quarterly", 8) == dt.date(2028, 1, 1)


def test_forecast_points_land_on_the_first_of_the_period():
    # Every stored observation is normalised to the period's first day, so a
    # forecast that is not would render offset from the history it continues.
    for freq in ("annual", "monthly", "quarterly"):
        assert advance(dt.date(2026, 6, 1), freq, 3).day == 1


# ── plausibility guard ───────────────────────────────────────────────────────


def test_guard_rejects_non_finite_forecasts():
    result = ForecastResult("chronos2", [math.nan, 1.0], [0.0, 0.0], [2.0, 2.0])
    with pytest.raises(ForecastRejected, match="NaN or infinity"):
        _check_plausible(RISING, result)


def test_guard_rejects_a_numerical_blow_up():
    result = ForecastResult("chronos2", [1e12] * 5, [0.0] * 5, [1e13] * 5)
    with pytest.raises(ForecastRejected, match="drifts"):
        _check_plausible(RISING, result)


def test_guard_allows_a_large_but_real_move():
    # The same boundary connectors/validation.py draws: reject the impossible, not
    # the surprising. A doubling is surprising; it is not impossible.
    last = RISING[-1]
    result = ForecastResult("chronos2", [last * 2] * 5, [last] * 5, [last * 3] * 5)
    _check_plausible(RISING, result)  # must not raise


def test_modal_response_with_ragged_quantiles_is_rejected():
    with pytest.raises(ForecastRejected, match="ragged"):
        _from_modal(
            {"model": "chronos2", "median": [1, 2], "lower": [1], "upper": [1, 2]}, "chronos2"
        )


def test_modal_response_missing_a_band_is_rejected():
    with pytest.raises(ForecastRejected, match="malformed"):
        _from_modal({"model": "chronos2", "median": [1.0]}, "chronos2")


# ── the cascade ──────────────────────────────────────────────────────────────


async def test_cascade_prefers_chronos2(monkeypatch):
    async def fake_call(function_name, *_args):
        assert function_name == "chronos2_forecast"
        return _payload("chronos2")

    monkeypatch.setattr(forecasting.modal_client, "call", fake_call)
    result = await ForecastingService().predict(RISING, horizon=5)
    assert result.model_used == "chronos2"
    assert result.attempts == ()


async def test_cascade_falls_back_to_timesfm_when_chronos2_fails(monkeypatch):
    async def fake_call(function_name, *_args):
        if function_name == "chronos2_forecast":
            raise ModalUnavailable("chronos2 exceeded 420.0s")
        return _payload("timesfm")

    monkeypatch.setattr(forecasting.modal_client, "call", fake_call)
    result = await ForecastingService().predict(RISING, horizon=5)
    assert result.model_used == "timesfm"
    assert "chronos2" in result.attempts[0]


async def test_cascade_falls_back_to_statsforecast_when_modal_is_entirely_down(monkeypatch):
    """The decision #22 case: Modal unreachable must still yield a forecast.

    This is the reason StatsForecast runs on the VPS rather than on Modal with the
    other two — if it were remote, a Modal outage would take the whole cascade down.
    """

    async def fake_call(*_args):
        raise ModalUnavailable("Modal is unreachable")

    monkeypatch.setattr(forecasting.modal_client, "call", fake_call)
    result = await ForecastingService().predict(RISING, horizon=5, seasonality=1)

    assert result.model_used == "statsforecast"
    assert len(result.median) == len(result.lower) == len(result.upper) == 5
    assert all(math.isfinite(v) for v in result.median)
    # A rising series must not be projected below where it has already been.
    assert min(result.median) > min(RISING)
    # p10 <= median <= p90, or the bands are meaningless.
    assert all(
        lo <= m <= hi for lo, m, hi in zip(result.lower, result.median, result.upper, strict=True)
    )
    assert len(result.attempts) == 2


async def test_cascade_reports_every_failure_when_it_is_exhausted(monkeypatch):
    async def fake_call(*_args):
        raise ModalUnavailable("down")

    def broken_statsforecast(*_args):
        raise RuntimeError("no local model either")

    monkeypatch.setattr(forecasting.modal_client, "call", fake_call)
    monkeypatch.setattr(forecasting, "_statsforecast_sync", broken_statsforecast)

    with pytest.raises(ForecastUnavailable) as exc:
        await ForecastingService().predict(RISING, horizon=5)
    for model in ForecastingService.MODEL_CASCADE:
        assert model in str(exc.value)


async def test_a_model_returning_nonsense_hands_over_rather_than_being_stored(monkeypatch):
    async def fake_call(function_name, *_args):
        if function_name == "chronos2_forecast":
            return {
                "model": "chronos2",
                "median": [math.inf] * 5,
                "lower": [0.0] * 5,
                "upper": [0.0] * 5,
            }
        return _payload("timesfm")

    monkeypatch.setattr(forecasting.modal_client, "call", fake_call)
    result = await ForecastingService().predict(RISING, horizon=5)
    assert result.model_used == "timesfm"
    assert "NaN or infinity" in result.attempts[0]


async def test_a_series_too_short_to_forecast_is_refused():
    with pytest.raises(ForecastUnavailable, match="below the"):
        await ForecastingService().predict([1.0, 2.0, 3.0], horizon=5)


def test_the_cascade_order_is_the_documented_one():
    # CLAUDE.md hard rule: reordering requires an architecture.md update, so pin it.
    assert ForecastingService.MODEL_CASCADE == ("chronos2", "timesfm", "statsforecast")


# ── caching (feature 2.5) ────────────────────────────────────────────────────


def test_cache_key_changes_when_the_series_gains_an_observation():
    """features.md 2.5's stale-after-source-correction case, closed structurally."""
    before = forecast_cache_key("NGA", "FP.CPI.TOTL.ZG", dt.date(2025, 1, 1), 60, 5)
    after = forecast_cache_key("NGA", "FP.CPI.TOTL.ZG", dt.date(2026, 1, 1), 61, 5)
    assert before != after


def test_cache_key_distinguishes_similar_requests():
    """The documented "similar but distinct requests" collision case."""
    keys = {
        forecast_cache_key("NGA", "FP.CPI.TOTL.ZG", dt.date(2025, 1, 1), 60, 5),
        forecast_cache_key("NGA", "FP.CPI.TOTL.ZG", dt.date(2025, 1, 1), 60, 12),
        forecast_cache_key("GHA", "FP.CPI.TOTL.ZG", dt.date(2025, 1, 1), 60, 5),
        forecast_cache_key("NGA", "NY.GDP.MKTP.KD.ZG", dt.date(2025, 1, 1), 60, 5),
    }
    assert len(keys) == 4


def test_cache_key_is_readable_enough_to_invalidate_by_prefix():
    key = forecast_cache_key("NGA", "FP.CPI.TOTL.ZG", dt.date(2025, 1, 1), 60, 5)
    assert key.startswith("forecast:NGA:FP.CPI.TOTL.ZG:")
