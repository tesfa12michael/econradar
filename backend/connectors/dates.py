"""Frequency-aware observation-date parsing, shared by every connector.

Phase 1 handled annual dates only and rejected anything sub-annual. Phase 2 needs
monthly and quarterly too: BIS policy rates are monthly (``2026-04``), the World Bank
Global Economic Monitor is monthly in the World Bank's own ``2025M06`` spelling, and
FRED returns full ISO dates (``2025-06-01``).

Every period normalizes to **the first day of the period** so a single ``date`` column
can hold mixed frequencies without ambiguity, and the parsed frequency travels
alongside the date so it can be recorded on ``indicators_catalog.frequency``.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Final

ANNUAL: Final = "annual"
QUARTERLY: Final = "quarterly"
MONTHLY: Final = "monthly"
DAILY: Final = "daily"

#: Ordered longest-first so a more specific pattern is never shadowed by a looser one.
_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), DAILY),
    (re.compile(r"^(\d{4})-?Q([1-4])$", re.IGNORECASE), QUARTERLY),
    (re.compile(r"^(\d{4})-?M(\d{1,2})$", re.IGNORECASE), MONTHLY),
    (re.compile(r"^(\d{4})-(\d{1,2})$"), MONTHLY),
    (re.compile(r"^(\d{4})$"), ANNUAL),
)


class UnparseableDate(ValueError):
    """The raw period string matched no known frequency format."""


def parse_period(raw: object) -> tuple[dt.date, str]:
    """Parse a provider period string into ``(first_day_of_period, frequency)``.

    Raises UnparseableDate for anything unrecognized — callers turn that into a
    NormalizationError so the offending record reaches ``etl_errors`` rather than
    being dropped.
    """
    s = str(raw or "").strip()
    if not s:
        raise UnparseableDate("empty period")

    for pattern, frequency in _PATTERNS:
        match = pattern.match(s)
        if match is None:
            continue
        try:
            return _build(match, frequency), frequency
        except ValueError as exc:  # e.g. month 13, day 31 in a 30-day month
            raise UnparseableDate(f"invalid {frequency} period {s!r}: {exc}") from exc

    raise UnparseableDate(f"unrecognized period format: {s!r}")


def _build(match: re.Match[str], frequency: str) -> dt.date:
    year = int(match.group(1))
    if frequency == ANNUAL:
        return dt.date(year, 1, 1)
    if frequency == QUARTERLY:
        return dt.date(year, (int(match.group(2)) - 1) * 3 + 1, 1)
    if frequency == MONTHLY:
        return dt.date(year, int(match.group(2)), 1)
    return dt.date(year, int(match.group(2)), int(match.group(3)))
