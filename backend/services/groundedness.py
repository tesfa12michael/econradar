"""Groundedness verification — the programmatic enforcement of decision #8.

CLAUDE.md's defining constraint is that an LLM *narrates* precomputed numbers and
never generates, estimates or approximates one. That is a promise about output, so
it is checked on output: every numeric literal a model emits is extracted and
matched against the numbers it was given. Anything unmatched is a fabrication, and
a narration containing one is not served.

**What this catches:** any digit-bearing figure the model invented, mis-copied,
mis-rounded, or computed for itself (a growth rate, a difference, an average that
was not supplied).

**What it could never catch on its own**, and what `services/semantics.py` was
added to catch beside it (decisions #32-#34): a figure copied perfectly and then
*read wrong* — a spike described as a drop, a level presented as the size of a
change, a hyperinflation-era rate quoted as though it sat on today's scale. Those
answers score 1.00 here and are false. `verify()` therefore runs both and requires
both; see `GroundednessReport.passed`.

**Arithmetic the reader can check** (decision #41). "Copied from the evidence" was
too narrow a definition of grounded. Japan at 2.5% and Germany at 3.7%, both read
out of tool results, make "a gap of 1.2 percentage points" a fact — and the first
version of this module retracted the whole answer over it, because 1.2 was not in
the context. So a figure that is *not* in the evidence gets a second test: is it
exact arithmetic on figures quoted right beside it? A difference, a sum, a mean, a
ratio or a percentage change, recomputed here and required to reproduce the digits
as written. Locality is the safety property — the model has shown its working, the
reader can check it without looking elsewhere, and nothing can be derived from a
number that was itself invented. Arithmetic that is merely *asserted* still fails:
"2.5% against 3.7% is a gap of 4.4 points" is rejected exactly as before.

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
largest") and treating them as claims would reject honest narration. A ratio word
is cleared by the same rule as a derived figure: quote both numbers beside it and
the multiple is checked rather than assumed.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass, field
from typing import Any

from config import settings
from logging_config import get_logger
from services.semantics import SemanticReport, check_semantics

logger = get_logger(__name__)

# Digit-bearing figures only. Thousands separators and a leading sign are consumed
# so "$1,234.5" and "-2.1%" each yield one number rather than three.
_NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w])[-+]?\d*\.?\d+")

# Ratio and multiple vocabulary. Each asserts a computed relationship between two
# numbers — a numeric claim carrying no digits for the extractor to check.
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

#: The multiple each term claims, where it claims a definite one. A term in this
#: map is cleared when the sentence quotes two grounded figures whose ratio matches;
#: "an order of magnitude" is deliberately absent, because it names a range rather
#: than a number and there is nothing to check it against.
RATIO_TERMS: dict[str, float] = {
    "half": 0.5,
    "a third": 1 / 3,
    "a quarter": 0.25,
    "a fifth": 0.2,
    "double": 2.0,
    "doubled": 2.0,
    "twice": 2.0,
    "triple": 3.0,
    "tripled": 3.0,
    "threefold": 3.0,
    "tenfold": 10.0,
}

#: Ratio words are approximations by construction — "roughly double" for 1.96 is
#: honest English, and holding it to the 0.5% tolerance used for copied digits would
#: reject the ordinary use of the word. The band is wider *because* both operands are
#: on the page: the reader is being offered a summary of visible arithmetic, not a
#: figure they have to take on trust.
RATIO_WORD_TOLERANCE = 0.10

#: "the second half of 2025" is a period, not a ratio. Without this the word alone
#: fails an otherwise correct answer.
_PERIOD_HALF_RE = re.compile(
    r"\b(?:first|second|latter|later|earlier|1st|2nd)\s+half\b|\bhalf\s+of\s+(?:19|20)\d\d\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

#: Beyond this many figures, the text is a list — a top-ten ranking, a table row —
#: not a derivation, and every extra operand multiplies the set of values that would
#: count as "derived". Capped so the second chance stays a second chance rather than
#: becoming a way for any number to look reachable.
MAX_DERIVATION_OPERANDS = 6

#: Sentences a derivation may reach back over. One was too few, measured against a
#: real answer: "South Africa's was 32.4% in 2025, while Japan's was 2.5%. The gap is
#: 29.9 percentage points." is how the comparison actually gets written, and the
#: subtraction is exactly right. Two is where it stops — a reader checking a figure
#: looks at the line above it, not at the top of the answer.
DERIVATION_WINDOW_SENTENCES = 2


def _is_calendar_year(value: float) -> bool:
    """Years are labels, not quantities.

    Admitting them as operands means "2025 - 2.5" and "2025 / 2020" become candidate
    derivations, which is a hundred meaningless values for every meaningful one — and
    every one of them is another chance for an invented figure to land on something.
    The cost is that a span of years written in digits ("over the 5 years to 2025")
    is not derivable; that is a date range, and the prompt asks for the dates.
    """
    return float(value).is_integer() and 1800 <= value <= 2200


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
    semantic: SemanticReport = field(default_factory=SemanticReport)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Both disciplines, not either.

        A response that copies every figure correctly and then says the rate fell
        when the evidence says it rose is worse than one that fumbles a decimal: it
        is wrong in a way the reader has no way to detect. So the semantic report
        is a veto, not a score adjustment — mixing it into `score` would let a long
        answer average a contradiction away.
        """
        return self.score >= settings.groundedness_min_score and self.semantic.passed

    def reason(self) -> str:
        parts = []
        if self.ungrounded:
            parts.append("numbers absent from context: " + ", ".join(self.ungrounded))
        if self.approximations:
            parts.append("approximation terms: " + ", ".join(self.approximations))
        if not self.semantic.passed:
            parts.append(self.semantic.reason())
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


def derivations(operands: list[float]) -> set[float]:
    """Every value a reader could reproduce from these figures with one operation.

    Deliberately a short list. Differences, sums, means, ratios and percentage
    changes are what an analyst writes and what a reader checks; anything longer —
    a compound growth rate, a weighted average — is a calculation the model must not
    be doing in its head, and admitting it here would be admitting the failure this
    module exists to catch.
    """
    out: set[float] = set()
    for i, a in enumerate(operands):
        for b in operands[i + 1 :]:
            out.update({a - b, b - a, a + b, (a + b) / 2})
            if b:
                out.add(a / b)
                out.add((a - b) / b * 100)
            if a:
                out.add(b / a)
                out.add((b - a) / a * 100)
    return {value for value in out if math.isfinite(value)}


def _reproduces(literal: str, value: float, candidates: set[float]) -> bool:
    """Whether some candidate, written out, gives exactly the digits in `literal`.

    Not `_matches`. That function's 0.5% band is the right tolerance for a figure
    *copied* from the evidence and rounded for readability, and the wrong one here:
    a sentence quoting seven figures produces on the order of a hundred candidate
    derivations, and a ±0.5% window around each is enough for an invented number to
    land on one by chance. A test caught precisely that — "41.7%" was accepted as
    16.95 + 24.66 = 41.61, which it is not.

    So a derivation has to reproduce the digits the model actually wrote: the
    candidate must round to the literal at the precision the literal was given to.
    Half a unit in the last place, which is what rounding means, and nothing wider.
    """
    half_ulp = 0.5 * 10.0 ** -len(literal.partition(".")[2]) + 1e-9
    return any(
        abs(candidate / scale - value) <= half_ulp for candidate in candidates for scale in _SCALES
    )


def _derivable(text: str, allowed: set[float], tolerance: float) -> set[float]:
    """Ungrounded values that are exact arithmetic on grounded figures beside them.

    Over a short sliding window rather than the whole answer, because locality is
    what keeps this safe: the operands have to be in front of the reader. Across a
    whole answer, "some two numbers somewhere produce this" is barely a constraint,
    and each extra operand multiplies the candidate set.
    """
    rescued: set[float] = set()
    sentences = _SENTENCE_SPLIT_RE.split(text)
    for index, sentence in enumerate(sentences):
        pending = [
            (literal, value)
            for literal, value in extract_numbers(sentence)
            if not _matches(value, allowed, tolerance)
        ]
        if not pending:
            continue
        window = " ".join(sentences[max(0, index + 1 - DERIVATION_WINDOW_SENTENCES) : index + 1])
        operands = [
            value
            for _, value in extract_numbers(window)
            if _matches(value, allowed, tolerance) and not _is_calendar_year(value)
        ]
        if not 2 <= len(operands) <= MAX_DERIVATION_OPERANDS:
            continue
        candidates = derivations(operands)
        rescued.update(
            value for literal, value in pending if _reproduces(literal, value, candidates)
        )
    return rescued


def _approximation_terms(text: str, allowed: set[float], tolerance: float) -> tuple[str, ...]:
    """Ratio words that the sentence around them does not substantiate."""
    flagged: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        lowered = sentence.lower()
        operands = [
            value for _, value in extract_numbers(sentence) if _matches(value, allowed, tolerance)
        ]
        ratios = [a / b for a in operands for b in operands if b and a != b]
        for term in APPROXIMATION_TERMS:
            if not re.search(rf"\b{re.escape(term)}\b", lowered):
                continue
            if term == "half" and _PERIOD_HALF_RE.search(lowered):
                continue
            claimed = RATIO_TERMS.get(term)
            if claimed is not None and any(
                abs(ratio - claimed) <= RATIO_WORD_TOLERANCE * claimed for ratio in ratios
            ):
                continue
            flagged.append(term)
    return tuple(dict.fromkeys(flagged))


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

    # Copied first, derived second. A figure that is simply in the evidence never
    # needs the arithmetic path, so the common case costs nothing.
    unmatched = {value for _, value in numbers if not _matches(value, allowed, tol)}
    derived = _derivable(text, allowed, tol) if unmatched else set()
    ungrounded = tuple(
        literal for literal, value in numbers if value in unmatched and value not in derived
    )
    approximations = _approximation_terms(text, allowed, tol)

    # Meaning, not just arithmetic (decisions #32-#34). Run even when there are no
    # numbers to score: prose can still describe a rise as a fall.
    semantic = (
        check_semantics(text, context, tolerance=tol)
        if settings.semantic_checks_enabled
        else SemanticReport()
    )

    if not numbers:
        # Prose with no figures cannot fabricate one. It is trivially grounded — but
        # an approximation term is still a numeric claim, so it still fails.
        score = 0.0 if approximations else 1.0
        return GroundednessReport(
            score=score, total_numbers=0, approximations=approximations, semantic=semantic
        )

    grounded = len(numbers) - len(ungrounded)
    score = grounded / len(numbers)
    # Recorded, not silent. A figure accepted because the arithmetic checked out is
    # a weaker claim than one copied verbatim, and the log line should say when the
    # second path was used — "silent failures are never acceptable" applies to
    # silent acceptances too.
    if derived:
        logger.info(
            "groundedness: %d figure(s) accepted as arithmetic on figures in the same sentence: %s",
            len(derived),
            sorted(derived),
        )
    if approximations:
        score = min(score, 0.0)
    return GroundednessReport(
        score=round(score, 4),
        total_numbers=len(numbers),
        ungrounded=ungrounded,
        approximations=approximations,
        semantic=semantic,
        extra={"derived": sorted(derived)} if derived else {},
    )
