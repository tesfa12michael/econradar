"""Groundedness verification — the programmatic enforcement of decision #8.

CLAUDE.md's defining constraint is that an LLM *narrates* precomputed numbers and
never generates, estimates or approximates one. That is a promise about output, so
it is checked on output: every numeric literal a model emits is extracted and
matched against the numbers it was given. Anything unmatched is a fabrication, and
a narration containing one is not served.

**What this catches:** any digit-bearing figure the model invented, mis-copied,
mis-rounded, or computed for itself (a growth rate, a difference, an average that
was not supplied).

**What it deliberately does not do:** it does not repair. A response that fails is
discarded and the next provider is tried, because silently editing a model's prose
to match the data would make the verifier's own output unverifiable.

**Known limit, stated rather than papered over** (features.md 1.5 names it): a
number written in words — "roughly a fifth" instead of "20%" — carries no digits
and cannot be matched against the context. Two things address it. The prompt
requires digits copied verbatim, and `APPROXIMATION_TERMS` below flags the specific
vocabulary of computed ratios ("half", "double", "twice", "tenfold"), which are
numeric claims however they are spelled. Plain counting words ("one", "two") are
*not* flagged: they carry structural meaning in ordinary prose ("one of the
largest") and treating them as claims would reject honest narration.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass, field
from typing import Any

from config import settings

# Digit-bearing figures only. Thousands separators and a leading sign are consumed
# so "$1,234.5" and "-2.1%" each yield one number rather than three.
_NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w])[-+]?\d*\.?\d+")

# Ratio and multiple vocabulary. Each asserts a computed relationship between two
# numbers, which is arithmetic the model is not permitted to do.
APPROXIMATION_TERMS: tuple[str, ...] = (
    "half",
    "a third",
    "a quarter",
    "a fifth",
    "double",
    "doubled",
    "triple",
    "tripled",
    "twice",
    "threefold",
    "tenfold",
    "an order of magnitude",
)

# Rescalings a narrator may legitimately apply to a supplied value: writing
# 3.4 trillion for 3_400_000_000_000. Grounding these can only ever match a real
# number under a unit change, never invent one.
_SCALES: tuple[float, ...] = (1.0, 1e3, 1e6, 1e9, 1e12)


@dataclass(frozen=True, slots=True)
class GroundednessReport:
    score: float
    total_numbers: int
    ungrounded: tuple[str, ...] = ()
    approximations: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.score >= settings.groundedness_min_score

    def reason(self) -> str:
        parts = []
        if self.ungrounded:
            parts.append("numbers absent from context: " + ", ".join(self.ungrounded))
        if self.approximations:
            parts.append("approximation terms: " + ", ".join(self.approximations))
        return "; ".join(parts) or "grounded"


def extract_numbers(text: str) -> list[tuple[str, float]]:
    """Every digit-bearing figure in `text`, as (literal, value)."""
    found: list[tuple[str, float]] = []
    for match in _NUMBER_RE.finditer(text):
        raw = match.group(0)
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        found.append((raw, value))
    return found


def collect_allowed(context: Any) -> set[float]:
    """Every number the model was given, walked out of the context recursively.

    Dates contribute their year, month and day: a narration that says "in March
    2024" is quoting the context, and refusing it would fail honest prose.
    """
    allowed: set[float] = set()

    def walk(node: Any) -> None:
        if node is None or isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            if math.isfinite(node):
                allowed.add(float(node))
            return
        if isinstance(node, (dt.date, dt.datetime)):
            allowed.update({float(node.year), float(node.month), float(node.day)})
            return
        if isinstance(node, str):
            # ISO dates and any figure already formatted into a context string.
            for _, value in extract_numbers(node):
                allowed.add(value)
            return
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
            return
        if isinstance(node, (list, tuple, set)):
            for value in node:
                walk(value)

    walk(context)
    return allowed


def _matches(value: float, allowed: set[float], tolerance: float) -> bool:
    """True when `value` is a faithful rendering of some allowed number.

    Three ways to be faithful: identical, rounded to any sensible number of decimal
    places, or the same quantity at a different scale (billions for units). Nothing
    here can ground a number that is not derived from a supplied one.
    """
    for scale in _SCALES:
        target = value * scale
        for candidate in (target, value):
            for base in allowed:
                if base == candidate:
                    return True
                if abs(base - candidate) <= max(tolerance * abs(base), 1e-9):
                    return True
                # The narrator rounded: 3.42 -> "3.4", 1234.7 -> "1,235".
                for places in range(0, 5):
                    if round(base, places) == candidate:
                        return True
                if (
                    scale > 1.0
                    and base != 0
                    and abs(base / scale - value) <= max(tolerance * abs(base / scale), 1e-9)
                ):
                    return True
    return False


def verify(text: str, context: Any, *, tolerance: float | None = None) -> GroundednessReport:
    """Score `text` against the numbers in `context`.

    Score is the share of extracted figures that match, minus nothing — an
    approximation term does not reduce the ratio, it fails the report outright by
    forcing the score below any threshold. Both failures are reported separately so
    a log line says which discipline was broken.
    """
    tol = settings.groundedness_tolerance if tolerance is None else tolerance
    allowed = collect_allowed(context)
    numbers = extract_numbers(text)

    ungrounded = tuple(literal for literal, value in numbers if not _matches(value, allowed, tol))
    lowered = text.lower()
    approximations = tuple(term for term in APPROXIMATION_TERMS if term in lowered)

    if not numbers:
        # Prose with no figures cannot fabricate one. It is trivially grounded — but
        # an approximation term is still a numeric claim, so it still fails.
        score = 0.0 if approximations else 1.0
        return GroundednessReport(score=score, total_numbers=0, approximations=approximations)

    grounded = len(numbers) - len(ungrounded)
    score = grounded / len(numbers)
    if approximations:
        score = min(score, 0.0)
    return GroundednessReport(
        score=round(score, 4),
        total_numbers=len(numbers),
        ungrounded=ungrounded,
        approximations=approximations,
    )
