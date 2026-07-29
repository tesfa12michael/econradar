"""Statistical anomaly detection (feature 1.8).

Rolling Z-score with an IQR cross-check, run automatically after every ingestion.
This is the *statistical* half of the boundary documented in
`connectors/validation.py`: ETL has already rejected the impossible, so everything
reaching this module is real data. The job here is to flag what is surprising —
never to reject it.

**No LLM involvement.** Magnitude, direction and timestamp only; the grounded
narrative explanation is feature 2.3 in Phase 3.

Scores are taken against a **local linear trend**, not against the window's level.
Comparing a value to its recent average flags every point of a trending series: GDP per
capita only ever rises, so each new observation sits above the trailing median by
construction, and a level-based score flagged 204 of 214 countries. What matters is
whether a point departs from where the recent trend was heading, so the window is fitted
with least squares, the next value predicted, and the *residual* scored.

Three edge cases from features.md shape the rest:

* *"The first few points of a new series lack enough history for a meaningful rolling
  Z-score."* Scoring starts only once `min_observations` points precede a value, and
  the window is strictly backward-looking so a point is never scored against its own
  future.
* *"A naturally volatile indicator may falsely flag constantly under a fixed
  threshold."* A plain standard deviation is itself distorted by the outliers it is
  meant to find, so spread is estimated from the **MAD of the fit residuals**, which a
  single extreme point cannot inflate. A candidate must additionally fall outside the
  residuals' Tukey IQR fence, so volatile-but-consistent series stay quiet.
* A perfectly flat window has no residual spread at all, making a Z-score undefined
  rather than large — the normal shape of a held policy rate. See `detect`.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from config import settings

#: Scale factor making the median absolute deviation a consistent estimator of sigma
#: for normally-distributed data (1 / 0.6745).
_MAD_TO_SIGMA: Final = 1.4826

#: Tukey's constant for the outer fence used as the corroborating check.
_IQR_MULTIPLIER: Final = 1.5

SPIKE = "spike"
DROP = "drop"
STRUCTURAL_BREAK = "structural_break"

#: Relative tolerance for "the window is genuinely flat" comparisons, so floating-point
#: noise in a held rate is not mistaken for a policy move.
_FLAT_TOLERANCE: Final = 1e-9

#: How many times a series' typical step a break must exceed to count as anomalous.
#: See _is_large_move — this is what stops routine rate decisions flooding the map.
_BREAK_STEP_MULTIPLE: Final = 3.0

#: Residual spread below this fraction of the series' scale is treated as *no* spread.
#: A window that the trend fits almost perfectly (a held rate, or a rate climbing in
#: identical steps) yields a sigma near zero, which would turn any deviation into an
#: enormous Z-score. Such a window is not "extremely precise" — the Z-score machinery
#: simply does not apply, so those points go to the step-magnitude test instead.
_SIGMA_EPSILON: Final = 1e-6


@dataclass(frozen=True, slots=True)
class Observation:
    date: dt.date
    value: float


@dataclass(frozen=True, slots=True)
class Anomaly:
    date: dt.date
    value: float
    #: None for a structural break out of a perfectly flat window, where a Z-score is
    #: mathematically undefined (zero spread) rather than merely large.
    z_score: float | None
    deviation_type: str


def _robust_sigma(residuals: Sequence[float]) -> float:
    """MAD estimate of sigma from fit residuals, resistant to the outliers we hunt."""
    mad = statistics.median([abs(r) for r in residuals])
    if mad > 0:
        return mad * _MAD_TO_SIGMA
    # Residuals that are all zero mean a perfectly clean fit (a flat or perfectly
    # linear window); fall back to stdev so a genuine step is still detectable.
    return statistics.pstdev(residuals) if len(residuals) > 1 else 0.0


@dataclass(frozen=True, slots=True)
class _Fit:
    """A local trend fitted to one window."""

    #: Prediction for the next point, in the series' original units.
    predicted: float
    #: Fit residuals, in whichever space the fit was performed.
    residuals: list[float]
    log_space: bool

    def residual_of(self, value: float) -> float:
        if self.log_space and value > 0 and self.predicted > 0:
            return math.log(value) - math.log(self.predicted)
        return value - self.predicted


def _local_trend(window: Sequence[float]) -> _Fit:
    """Fit the window with least squares, in log space when the series is positive.

    A linear fit is what makes a trending series scoreable at all: without it, "above
    the recent average" and "unusual" are the same statement. But economic levels grow
    *multiplicatively* — GDP per capita compounds — and a straight line through a curve
    leaves residuals that grow with the trend, which reintroduces the false flags.
    Fitting log values turns exponential growth into a straight line and makes residuals
    relative, so steady compounding scores as unremarkable.

    Log space needs strictly positive values, so rates and balances that cross zero
    (inflation, GDP growth, current account) are fitted linearly — which is right for
    them anyway, since those series are already changes rather than levels.
    """
    log_space = all(v > 0 for v in window)
    values = [math.log(v) for v in window] if log_space else list(window)
    xs = list(range(len(values)))

    try:
        slope, intercept = statistics.linear_regression(xs, values)
    except statistics.StatisticsError:  # degenerate window (fewer than two points)
        median = statistics.median(values)
        slope, intercept = 0.0, median

    residuals = [v - (intercept + slope * x) for v, x in zip(values, xs, strict=True)]
    predicted = intercept + slope * len(values)
    return _Fit(
        predicted=math.exp(predicted) if log_space else predicted,
        residuals=residuals,
        log_space=log_space,
    )


def _differs(value: float, centre: float) -> bool:
    """True when a value has genuinely moved off a flat window, ignoring FP noise."""
    return abs(value - centre) > max(abs(centre), 1.0) * _FLAT_TOLERANCE


def _is_large_move(series: Sequence[Observation], index: int, value: float, centre: float) -> bool:
    """True when a step off a flat window is big by that series' own standards.

    A policy rate stepping 25bp after a hold is ordinary; the same series jumping
    several percentage points is not. Comparing against the median absolute step over
    the series' full history keeps the test scale-free, so it works equally for a rate
    that moves in quarter-points and one that moves in hundreds.
    """
    # Strictly prior steps: including the current one would make every move its own
    # baseline, so nothing could ever be large relative to it.
    steps = [
        abs(series[i].value - series[i - 1].value)
        for i in range(1, index)
        if series[i].value != series[i - 1].value
    ]
    if not steps:
        return True  # the series has never moved before; this first move is notable
    typical = statistics.median(steps)
    if typical <= 0:
        return True
    return abs(value - centre) >= typical * _BREAK_STEP_MULTIPLE


def _iqr_fence(window: Sequence[float]) -> tuple[float, float]:
    ordered = sorted(window)
    midpoint = len(ordered) // 2
    lower_half = ordered[:midpoint]
    upper_half = ordered[midpoint + 1 :] if len(ordered) % 2 else ordered[midpoint:]
    if not lower_half or not upper_half:
        return float("-inf"), float("inf")
    q1 = statistics.median(lower_half)
    q3 = statistics.median(upper_half)
    spread = (q3 - q1) * _IQR_MULTIPLIER
    return q1 - spread, q3 + spread


def detect(
    observations: Sequence[Observation],
    *,
    threshold: float | None = None,
    window_size: int | None = None,
    min_observations: int | None = None,
) -> list[Anomaly]:
    """Flag observations that deviate from their recent history.

    Every parameter falls back to settings, so the threshold is configurable rather
    than hardcoded (an explicit acceptance criterion).
    """
    threshold = settings.anomaly_z_threshold if threshold is None else threshold
    window_size = settings.anomaly_window if window_size is None else window_size
    min_observations = (
        settings.anomaly_min_observations if min_observations is None else min_observations
    )

    series = sorted(observations, key=lambda o: o.date)
    found: list[Anomaly] = []

    for index, current in enumerate(series):
        if index < min_observations:
            continue  # not enough history for the score to mean anything

        window = [o.value for o in series[max(0, index - window_size) : index]]
        fit = _local_trend(window)
        predicted = fit.predicted
        sigma = _robust_sigma(fit.residuals)

        # In log space residuals are already relative, so the floor is absolute.
        floor = _SIGMA_EPSILON if fit.log_space else max(abs(predicted), 1.0) * _SIGMA_EPSILON
        if sigma <= floor:
            # A perfectly flat (or perfectly linear) window leaves no residual spread,
            # so a Z-score is undefined rather than large. This is the normal shape of a
            # held policy rate — but a central bank moving rates is routine, not
            # anomalous, and flagging every step produced ~68 "anomalies" per BIS
            # series. So the break must also be large relative to how that series
            # normally moves.
            if _differs(current.value, predicted) and _is_large_move(
                series, index, current.value, predicted
            ):
                found.append(
                    Anomaly(
                        date=current.date,
                        value=current.value,
                        z_score=None,
                        deviation_type=STRUCTURAL_BREAK,
                    )
                )
            continue

        residual = fit.residual_of(current.value)
        z_score = residual / sigma
        if abs(z_score) < threshold:
            continue

        low, high = _iqr_fence(fit.residuals)
        if low <= residual <= high:
            continue  # volatile but within its own spread — not an anomaly

        found.append(
            Anomaly(
                date=current.date,
                value=current.value,
                z_score=round(z_score, 4),
                deviation_type=SPIKE if z_score > 0 else DROP,
            )
        )

    return found
