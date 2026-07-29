"""Per-record ETL validation rules (feature 1.2).

**The boundary this module defends** (features.md calls out that it must stay
documented): *ETL rejects the impossible; anomaly detection flags the surprising.*

A current-account balance of 10^12 % of GDP is arithmetically impossible — it is a
parsing or unit error, so it is rejected here and written to ``etl_errors``. Nigeria's
inflation jumping twenty points in a year is entirely possible and entirely real; it is
not an ETL concern at all, and belongs to the rolling Z-score in
``services/anomaly.py`` (feature 1.8). Nothing statistical happens in this module.

Bounds are deliberately generous. They exist to catch broken data, not to second-guess
economics, so real extremes must survive: Zimbabwe's 2008 CPI inflation of ~24,411 %
and Luxembourg's exports at ~200 % of GDP are both valid observations. Bounds are
applied **only** to indicators whose semantics a connector has explicitly declared —
an unknown indicator gets the universal checks (finite, plausible date) and nothing
more, because guessing at a unit is how real data gets silently dropped.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from schemas import TimeSeriesRecord


class ValidationError(Exception):
    """A normalized record failed a validation rule. Routed to ``etl_errors``."""


class DuplicateRecord(ValidationError):
    """The same (country, indicator, date) appeared twice in one pipeline run.

    Subclasses ValidationError so overlapping re-runs and provider pagination bugs are
    logged as rejects rather than silently collapsing during upsert.
    """


class ValueKind(StrEnum):
    """What a number *means*, which is what makes a bound defensible."""

    PERCENT_CHANGE = "percent_change"  # growth rates, inflation
    PERCENT_SHARE = "percent_share"  # % of GDP, % of labor force
    RATE = "rate"  # policy / interest rates
    INDEX = "index"  # price and volume indices
    CURRENCY = "currency"  # levels in US$ or LCU, exchange rates
    COUNT = "count"  # headcounts, absolute quantities


@dataclass(frozen=True, slots=True)
class Bounds:
    low: float
    high: float
    why: str


#: Wide enough that every real observation we know of passes.
_BOUNDS: Final[dict[ValueKind, Bounds]] = {
    # -100 % is total collapse; the ceiling clears Zimbabwe 2008 (~24,411 %) with room.
    ValueKind.PERCENT_CHANGE: Bounds(-100.0, 1e7, "a percent change outside -100%..1e7%"),
    # Small open economies run trade well above 100 % of GDP; 1000 is still absurd.
    ValueKind.PERCENT_SHARE: Bounds(-1_000.0, 1_000.0, "a percent-of-total outside -1000%..1000%"),
    # Negative policy rates exist (SNB, ECB). The ceiling has to clear hyperinflation-era
    # overnight rates, which genuinely reached five figures: BIS carries Brazilian and
    # Turkish policy rates above 15,000% from the early 1990s. An earlier 1000% ceiling
    # rejected 61 real observations — precisely the second-guessing this module warns
    # against — so the bound now only excludes the arithmetically absurd.
    ValueKind.RATE: Bounds(-50.0, 1e6, "an interest rate outside -50%..1e6%"),
    ValueKind.INDEX: Bounds(0.0, 1e12, "a negative or absurdly large index level"),
    ValueKind.CURRENCY: Bounds(-1e15, 1e15, "a currency amount beyond +/-1e15"),
    ValueKind.COUNT: Bounds(0.0, 1e12, "a negative or absurdly large count"),
}


def check_value(value: float, kind: ValueKind | None) -> None:
    """Universal numeric checks, plus semantic bounds when the kind is known."""
    if math.isnan(value) or math.isinf(value):
        raise ValidationError(f"value is not finite: {value!r}")
    if kind is None:
        return
    bounds = _BOUNDS[kind]
    if not (bounds.low <= value <= bounds.high):
        raise ValidationError(f"implausible {kind.value}: {value!r} is {bounds.why}")


def check_date(date: dt.date, *, today: dt.date | None = None) -> None:
    """Reject dates that cannot describe a historical observation.

    The future bound is one full year ahead rather than "today" because annual series
    are stamped to 1 January and a current-year estimate is legitimate history. IMF
    WEO *projections* run years further out; connectors skip those at normalize time
    so they never reach this check and never pollute ``etl_errors``.
    """
    today = today or dt.date.today()
    if date.year > today.year + 1:
        raise ValidationError(f"date is implausibly far in the future: {date}")
    if date.year < 1900:
        raise ValidationError(f"date predates modern economic statistics: {date}")


def validate_record(
    record: TimeSeriesRecord,
    kind: ValueKind | None = None,
    *,
    today: dt.date | None = None,
) -> TimeSeriesRecord:
    """Run every per-record rule and return the record marked validated."""
    check_value(record.value, kind)
    check_date(record.date, today=today)
    return record.model_copy(update={"is_validated": True})
