"""Feature 1.8 — statistical anomaly detection.

Covers the two edge cases features.md calls out: a volatile series must not flag
constantly, and the opening points of a series must not be scored against history
they do not have.
"""

from __future__ import annotations

import datetime as dt

from services.anomaly import DROP, SPIKE, STRUCTURAL_BREAK, Observation, detect


def _series(values: list[float], start_year: int = 2000) -> list[Observation]:
    return [Observation(dt.date(start_year + i, 1, 1), v) for i, v in enumerate(values)]


def test_obvious_spike_is_flagged() -> None:
    found = detect(_series([2.0, 2.2, 1.8, 2.1, 1.9, 2.0, 2.3, 1.7, 2.0, 2.1, 40.0]))
    assert len(found) == 1
    assert found[0].deviation_type == SPIKE
    assert found[0].value == 40.0
    assert found[0].z_score is not None


def test_large_step_off_a_held_policy_rate_is_a_structural_break() -> None:
    """A held rate has zero spread, so a Z-score is undefined — but the move is real.

    This is the normal shape of BIS/FRED policy-rate data.
    """
    found = detect(_series([4.25] * 12 + [12.0]))
    assert len(found) == 1
    assert found[0].deviation_type == STRUCTURAL_BREAK
    assert found[0].z_score is None
    assert found[0].value == 12.0


def test_routine_rate_decisions_are_mostly_not_flagged() -> None:
    """A central bank moving in its usual increments is doing its job, not misbehaving.

    An early version flagged every move out of a flat window, which produced ~68
    "anomalies" per BIS series — one per rate decision. A realistic policy path of
    holds and quarter-point moves should stay near-silent. Not asserted as exactly
    zero: a genuine break in a hiking cycle is a legitimate inflection, and this
    guards against a flood, not against ever flagging.
    """
    path = [
        2.0, 2.0, 2.25, 2.25, 2.5, 2.5, 2.5, 2.25, 2.0, 2.0,
        2.25, 2.5, 2.75, 2.75, 2.5, 2.25, 2.25, 2.0, 2.0, 2.25,
    ]  # fmt: skip
    found = detect(_series(path))
    assert len(found) <= 1, f"expected a near-silent policy path, got {found}"


def test_obvious_drop_is_flagged() -> None:
    found = detect(_series([5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0, -30.0]))
    assert [a.deviation_type for a in found] == [DROP]


def test_stable_series_produces_nothing() -> None:
    assert detect(_series([3.0, 3.1, 2.9, 3.0, 3.2, 2.8, 3.0, 3.1, 2.9, 3.0, 3.05])) == []


def test_perfectly_flat_series_produces_nothing() -> None:
    """A zero-spread window would divide by zero; it must be skipped, not crash."""
    assert detect(_series([4.0] * 15)) == []


def test_early_points_are_never_scored() -> None:
    """The first points lack the history for a rolling score to mean anything."""
    found = detect(_series([100.0, 1.0, 1.0, 1.0, 1.0]), min_observations=8)
    assert found == []


def test_volatile_series_does_not_flag_constantly() -> None:
    """A naturally swingy indicator must stay quiet under a fixed threshold."""
    volatile = [10.0, -8.0, 12.0, -6.0, 9.0, -11.0, 14.0, -7.0, 11.0, -9.0, 13.0, -8.0]
    found = detect(_series([*volatile, 12.5]))
    assert found == [], "a value inside the series' own swing range is not an anomaly"


def test_outlier_resistant_to_a_contaminated_window() -> None:
    """A single huge earlier point must not inflate spread and mask a later anomaly.

    This is why the score uses median/MAD rather than mean/stdev: one outlier in the
    window would raise a plain standard deviation enough to hide the next one.
    """
    values = [2.0, 2.1, 1.9, 2.0, 500.0, 2.0, 2.1, 1.9, 2.0, 2.1, 300.0]
    found = detect(_series(values))
    assert any(a.value == 300.0 for a in found)


def test_threshold_is_configurable() -> None:
    values = [5.0, 5.2, 4.8, 5.1, 4.9, 5.0, 5.1, 4.9, 5.0, 6.4]
    assert detect(_series(values), threshold=50.0) == []
    assert detect(_series(values), threshold=1.0)


def test_results_carry_direction_and_magnitude() -> None:
    found = detect(_series([1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0, 25.0]))
    anomaly = found[0]
    assert anomaly.z_score > 0
    assert anomaly.deviation_type == SPIKE
    assert isinstance(anomaly.date, dt.date)


def test_unordered_input_is_sorted_before_scoring() -> None:
    ordered = _series([2.0] * 12 + [40.0])
    shuffled = [ordered[-1], *ordered[:-1]]
    assert detect(shuffled) == detect(ordered)


def test_empty_and_tiny_series_are_safe() -> None:
    assert detect([]) == []
    assert detect(_series([1.0])) == []


#: Compounding growth with mild, deterministic year-to-year wobble — the shape of a real
#: GDP-per-capita series rather than a noiseless curve.
_JITTER = [1.0, 1.02, 0.99, 1.01, 0.98, 1.03, 1.0, 0.99, 1.02, 0.98]


def _compounding(years: int, rate: float = 1.05, base: float = 1000.0) -> list[float]:
    return [base * rate**y * _JITTER[y % len(_JITTER)] for y in range(years)]


def test_a_steadily_trending_series_is_not_all_anomalies() -> None:
    """GDP per capita only ever rises, so every point beats the trailing average.

    Scoring levels instead of trend residuals flagged 204 of 214 countries on this
    exact indicator. Growth is not an anomaly.
    """
    assert detect(_series(_compounding(40))) == []


def test_a_break_in_a_trend_is_still_caught() -> None:
    """Trend-awareness must not blind the detector to a real collapse."""
    rising = _compounding(20)
    collapse = [*rising, rising[-1] * 0.5]  # a 50% fall after two decades of growth
    found = detect(_series(collapse))
    assert len(found) == 1
    assert found[0].value == collapse[-1]
    assert found[0].deviation_type in (DROP, STRUCTURAL_BREAK)
