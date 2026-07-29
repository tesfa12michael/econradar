"""Feature 1.2 — ETL validation rules and the ETL/anomaly boundary.

The boundary these tests pin down: ETL rejects the *impossible*, anomaly detection
flags the *surprising*. Real economic extremes must survive validation untouched.
"""

from __future__ import annotations

import datetime as dt

import pytest

from connectors.dates import UnparseableDate, parse_period
from connectors.validation import (
    ValidationError,
    ValueKind,
    check_date,
    check_value,
    validate_record,
)
from schemas import TimeSeriesRecord


def _rec(value: float, date: dt.date | None = None) -> TimeSeriesRecord:
    return TimeSeriesRecord(
        country_code="NGA",
        indicator_code="X",
        source_name="test",
        date=date or dt.date(2020, 1, 1),
        value=value,
    )


# ── date parsing ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected", "frequency"),
    [
        ("2025", dt.date(2025, 1, 1), "annual"),
        ("2025M06", dt.date(2025, 6, 1), "monthly"),
        ("2025m6", dt.date(2025, 6, 1), "monthly"),
        ("2026-04", dt.date(2026, 4, 1), "monthly"),
        ("2025Q1", dt.date(2025, 1, 1), "quarterly"),
        ("2025Q4", dt.date(2025, 10, 1), "quarterly"),
        ("2025-Q3", dt.date(2025, 7, 1), "quarterly"),
        ("2025-06-15", dt.date(2025, 6, 15), "daily"),
    ],
)
def test_parse_period(raw: str, expected: dt.date, frequency: str) -> None:
    date, freq = parse_period(raw)
    assert date == expected
    assert freq == frequency


@pytest.mark.parametrize("raw", ["", None, "garbage", "2025M13", "2025-02-30", "25"])
def test_parse_period_rejects_bad_input(raw: object) -> None:
    with pytest.raises(UnparseableDate):
        parse_period(raw)


def test_every_period_normalizes_to_first_day() -> None:
    """Mixed frequencies share one date column, so period starts must be unambiguous."""
    for raw in ("2025", "2025M06", "2025Q2"):
        assert parse_period(raw)[0].day == 1


# ── numeric plausibility ─────────────────────────────────────


def test_non_finite_always_rejected_even_without_a_known_kind() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            check_value(bad, None)


def test_unknown_kind_asserts_no_bounds() -> None:
    """Guessing at units silently drops real data — unknown means unbounded."""
    check_value(1e18, None)
    check_value(-1e18, None)


def test_impossible_values_rejected() -> None:
    with pytest.raises(ValidationError):
        check_value(1e12, ValueKind.PERCENT_SHARE)  # 10^12 % of GDP
    with pytest.raises(ValidationError):
        check_value(-5.0, ValueKind.COUNT)  # negative headcount
    with pytest.raises(ValidationError):
        check_value(-150.0, ValueKind.PERCENT_CHANGE)  # worse than total collapse


def test_real_economic_extremes_survive() -> None:
    """Regression guard: these are real observations, not data errors."""
    check_value(24_411.03, ValueKind.PERCENT_CHANGE)  # Zimbabwe CPI inflation, 2008
    check_value(203.0, ValueKind.PERCENT_SHARE)  # Luxembourg exports, % of GDP
    check_value(-0.75, ValueKind.RATE)  # negative policy rate (SNB)
    check_value(-23.4, ValueKind.PERCENT_CHANGE)  # Sudan real GDP growth, 2024
    # Real BIS observations that an earlier, tighter rate ceiling wrongly rejected.
    check_value(15_405.6, ValueKind.RATE)  # hyperinflation-era overnight policy rate
    check_value(2_741.2, ValueKind.RATE)


# ── dates ────────────────────────────────────────────────────


def test_future_dates_rejected_but_current_year_estimate_allowed() -> None:
    today = dt.date(2026, 7, 29)
    check_date(dt.date(2026, 1, 1), today=today)  # current-year estimate
    check_date(dt.date(2027, 1, 1), today=today)  # next-year estimate
    with pytest.raises(ValidationError):
        check_date(dt.date(2031, 1, 1), today=today)  # IMF projection horizon


def test_prehistoric_dates_rejected() -> None:
    with pytest.raises(ValidationError):
        check_date(dt.date(1850, 1, 1))


def test_validate_record_marks_validated() -> None:
    out = validate_record(_rec(5.0), ValueKind.PERCENT_CHANGE)
    assert out.is_validated is True
    assert out.value == 5.0
