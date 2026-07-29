"""Statistical anomaly detection (feature 1.8).

Rolling Z-score with an IQR cross-check, run automatically after every ingestion.
This is the *statistical* half of the boundary documented in
`connectors/validation.py`: ETL has already rejected the impossible, so everything
reaching this module is real data. The job here is to flag what is surprising —
never to reject it.

**No LLM involvement.** Magnitude, direction and timestamp only; the grounded
narrative explanation is feature 2.3 in Phase 3.

Two edge cases from features.md shape the design:

* *"The first few points of a new series lack enough history for a meaningful rolling
  Z-score."* Scoring starts only once `min_observations` points precede a value, and
  the window is strictly backward-looking so a point is never scored against its own
  future.
* *"A naturally volatile indicator may falsely flag constantly under a fixed
  threshold."* A plain standard deviation is itself distorted by the outliers it is
  meant to find, so the Z-score is computed against a **median/MAD** estimate, which a
  single extreme point cannot inflate. A candidate must additionally fall outside the
  window's Tukey IQR fence, so volatile-but-consistent series stay quiet.
"""

from __future__ import annotations

import datetime as dt
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


def _robust_sigma(window: Sequence[float], centre: float) -> float:
    """Median-absolute-deviation estimate of sigma, resistant to the outliers we hunt."""
    mad = statistics.median([abs(v - centre) for v in window])
    if mad > 0:
        return mad * _MAD_TO_SIGMA
    # A window that is entirely constant has no spread; fall back to stdev so a step
    # change out of a flat series is still detectable.
    return statistics.pstdev(window) if len(window) > 1 else 0.0


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
        centre = statistics.median(window)
        sigma = _robust_sigma(window, centre)

        if sigma <= 0:
            # A perfectly flat window has no spread, so a Z-score is undefined rather
            # than large. This is the normal shape of a held policy rate — but a
            # central bank moving rates is routine, not anomalous, and flagging every
            # step produced ~68 "anomalies" per BIS series. So the break must also be
            # large relative to how that series normally moves.
            if _differs(current.value, centre) and _is_large_move(
                series, index, current.value, centre
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

        z_score = (current.value - centre) / sigma
        if abs(z_score) < threshold:
            continue

        low, high = _iqr_fence(window)
        if low <= current.value <= high:
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
