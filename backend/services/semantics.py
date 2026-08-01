"""Meaning checks for text that has already passed the numeric verifier.

`groundedness.py` answers "did the model invent a number?". It cannot answer "did
the model understand what the number *means*?", and the second failure is the more
dangerous one, because output built from real stored values reads as trustworthy in
exactly the way invented output does not.

The failure that motivated this module, live and reproducible (decision #32):

    "Brazilian central bank policy rates reached a high of 355086.0% and had an
     anomaly of 70.8% in 1994-07-01, flagged as a drop. The policy rate dropped to
     21.0% in 2002-10-01."

Every figure there is real and every one is cited. It is also wrong three times
over. 70.8% is the level the rate fell **to** — from 15,406% the month before, when
the Real Plan ended hyperinflation — not a fall of 70.8%. The October 2002
observation is flagged in the evidence as a **spike**, z +21.1, and the answer says
it dropped. And 355,086% is a nominal annualised rate from a different currency and
a different monetary regime, quoted as though it belonged on the same axis as
today's 15%.

So three checks, each keyed to one of those failures:

* **Direction** — a figure the evidence marks as a rise must not be described with
  the vocabulary of a fall, and the reverse.
* **Level stated as change** — "a drop of 70.8%" when 70.8 is a level and the
  actual change was 15,335 points.
* **Unqualified extreme** — a value far outside any normal range for its unit
  carries a regime qualifier, or it is not served.

Every check is deliberately **conservative**: it fires only when a number in the
answer matches a fact the model was actually given, and only when the surrounding
sentence contradicts that fact outright. Ambiguity is resolved in the model's
favour, because a verifier that rejects honest prose gets switched off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from config import settings

# ── Vocabulary ───────────────────────────────────────────────────────────────

FALL_WORDS: frozenset[str] = frozenset(
    {
        "fell",
        "fall",
        "falls",
        "fallen",
        "falling",
        "dropped",
        "drop",
        "drops",
        "dropping",
        "declined",
        "decline",
        "declines",
        "declining",
        "decreased",
        "decrease",
        "decreases",
        "decreasing",
        "eased",
        "ease",
        "eases",
        "easing",
        "plunged",
        "plunge",
        "plunges",
        "plunging",
        "slid",
        "slide",
        "slides",
        "sliding",
        "sank",
        "sink",
        "sinks",
        "sinking",
        "tumbled",
        "tumble",
        "tumbles",
        "tumbling",
        "lowered",
        "lower",
        "lowers",
        "lowering",
        "cut",
        "cuts",
        "cutting",
        "reduced",
        "reduce",
        "reduces",
        "contracted",
        "contraction",
        "loosened",
        "loosening",
        "downward",
        "downwards",
        "weakened",
        "weakening",
    }
)

RISE_WORDS: frozenset[str] = frozenset(
    {
        "rose",
        "rise",
        "rises",
        "risen",
        "rising",
        "climbed",
        "climb",
        "climbs",
        "climbing",
        "increased",
        "increase",
        "increases",
        "increasing",
        "jumped",
        "jump",
        "jumps",
        "jumping",
        "spiked",
        "spike",
        "spikes",
        "spiking",
        "surged",
        "surge",
        "surges",
        "surging",
        "soared",
        "soar",
        "soars",
        "soaring",
        "grew",
        "grow",
        "grows",
        "growing",
        "growth",
        "raised",
        "raise",
        "raises",
        "raising",
        "higher",
        "highest",
        "upward",
        "upwards",
        "accelerated",
        "accelerating",
        "tightened",
        "tightening",
        "strengthened",
        "strengthening",
        "escalated",
        "escalating",
    }
)

#: Words that make an extreme figure honest by placing it in its own regime.
#: A reader who sees any of these knows the number is not on today's scale.
QUALIFIER_TERMS: tuple[str, ...] = (
    "hyperinflation",
    "hyperinflationary",
    "regime",
    "redenomination",
    "denominated",
    "currency reform",
    "currency change",
    "different currency",
    "nominal",
    "annualised",
    "annualized",
    "extraordinary",
    "not comparable",
    "incomparable",
    "not directly comparable",
    "era",
    "pre-stabilisation",
    "pre-stabilization",
    "stabilisation",
    "stabilization",
    "monetary reform",
)

_NUM = r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d*\.?\d+"

#: A direction word that *governs* a figure: "dropped to 21.0%", "eased to 7.04%".
#:
#: Sentence-level co-occurrence was tried first and was wrong. South Africa's
#: inflation peaked at 7.04% in 2022 and fell to 3.21% by 2025, so the correct
#: sentence "fell from 7.04% in 2022 to 3.21% in 2025" was rejected on the grounds
#: that 7.04 is itself flagged a spike — true, and irrelevant, because there the
#: value is where a later fall *started*. Requiring "to"/"at" ties the claim to the
#: figure it is actually about, and leaves "from" alone.
_DIRECTED_TO_RE = re.compile(
    rf"\b(?P<word>[a-z]+)\s+(?:to|at)\s+(?P<num>{_NUM})",
    re.IGNORECASE,
)

#: Nouns that unambiguously name the *size* of a move. Deliberately excludes
#: "spike", "surge", "peak" and friends: "a spike of 7%" is ordinary English for the
#: level reached, and reading it as a change would reject honest prose.
_CHANGE_NOUNS: frozenset[str] = frozenset(
    {
        "increase",
        "increases",
        "increased",
        "decrease",
        "decreases",
        "decreased",
        "rise",
        "rises",
        "rose",
        "fall",
        "falls",
        "fell",
        "decline",
        "declines",
        "declined",
        "drop",
        "drops",
        "dropped",
        "gain",
        "gains",
        "loss",
        "losses",
        "growth",
        "reduction",
        "change",
        "swing",
    }
)

#: Matched only with an explicit "of"/"by", so "fell to 70.8%" — a perfectly good
#: statement of a level — is never caught by this rule.
_CHANGE_OF_RE = re.compile(
    rf"\b(?P<word>[a-z]+)\s+(?:of|by)\s+(?P<num>{_NUM})",
    re.IGNORECASE,
)

#: A transition stated in prose: "fell from 15406.0% in 1994-06-01 to 70.8%".
#: Written for the RAG corpus that decision #40 retired, and kept because the
#: evidence a model is shown is not always structured — `comparability_notes` and
#: the anomaly `explanation` column are free text inside otherwise structured
#: contexts, and a directional claim in one of them should still bind the answer.
#: Deleting a verifier rule because its best-known producer is gone would be
#: loosening the check as a side effect of a cleanup.
_TRANSITION_RE = re.compile(
    r"\b(?P<dir>rose|fell)\s+from\s+"
    r"(?P<from>[-+]?[\d,]*\.?\d+)\s*\S*\s+in\s+(?P<from_date>\d{4}-\d{2}-\d{2})\s+to\s+"
    r"(?P<to>[-+]?[\d,]*\.?\d+)",
    re.IGNORECASE,
)

#: "a fall of 15,335 percentage points" / "a rise of 4.2 points"
_MAGNITUDE_RE = re.compile(
    r"\ba\s+(?P<dir>rise|fall)\s+of\s+(?P<num>[-+]?[\d,]*\.?\d+)",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

RISE, FALL = "rise", "fall"

#: spike/drop are the two `anomalies.deviation_type` values that carry a direction.
#: `structural_break` deliberately does not: a break is a change of regime, and
#: asserting a direction for it would be the same class of error this module exists
#: to catch.
_DEVIATION_DIRECTION: dict[str, str] = {
    "spike": RISE,
    "drop": FALL,
}


# ── Facts ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DirectionFact:
    value: float
    direction: str
    kind: str  # "level" | "change"
    origin: str


@dataclass(frozen=True, slots=True)
class SemanticReport:
    contradictions: tuple[str, ...] = ()
    level_as_change: tuple[str, ...] = ()
    unqualified_extremes: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not (self.contradictions or self.level_as_change or self.unqualified_extremes)

    def reason(self) -> str:
        parts = []
        if self.contradictions:
            parts.append("direction contradicts the evidence: " + "; ".join(self.contradictions))
        if self.level_as_change:
            parts.append("a level described as a change: " + "; ".join(self.level_as_change))
        if self.unqualified_extremes:
            parts.append(
                "extreme value stated without its regime qualifier: "
                + "; ".join(self.unqualified_extremes)
            )
        return " | ".join(parts) or "coherent"


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def is_extreme(value: float | None, unit: str | None) -> bool:
    """Whether a value is so far outside its unit's normal range that quoting it
    bare would mislead.

    Only percentages are judged. A GDP figure in US dollars is legitimately in the
    trillions and means exactly what it says; a *rate* of 355,086% does not belong
    on the same axis as 15% and cannot be read as though it does.
    """
    if value is None or unit != "%":
        return False
    return abs(value) >= settings.extreme_percent_threshold


def collect_direction_facts(context: Any) -> list[DirectionFact]:
    """Every directional claim the model was given, from wherever it was given.

    Walks the same context object the numeric verifier walks, so the two checks can
    never disagree about what the model saw. Structured contexts (anomaly
    explanations, chart interpretation, the agent's tool payloads) carry
    `deviation_type` and `changes`; free-text fields inside them are read for the
    prose phrasings below.
    """
    facts: list[DirectionFact] = []
    unit_hint: list[str | None] = [None]

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("unit") is not None:
                unit_hint[0] = node.get("unit")
            direction = _DEVIATION_DIRECTION.get(str(node.get("deviation_type") or "").lower())
            value = node.get("value")
            if direction and isinstance(value, (int, float)):
                facts.append(
                    DirectionFact(
                        value=float(value),
                        direction=direction,
                        kind="level",
                        origin=f"{node.get('date') or 'an observation'} is a {node.get('deviation_type')}",
                    )
                )
            changes = node.get("changes")
            if isinstance(changes, dict):
                for label, raw in changes.items():
                    delta = _to_float(str(raw))
                    if delta:
                        facts.append(
                            DirectionFact(
                                value=abs(delta),
                                direction=RISE if delta > 0 else FALL,
                                kind="change",
                                origin=str(label),
                            )
                        )
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple, set)):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            for match in _TRANSITION_RE.finditer(node):
                to_value = _to_float(match.group("to"))
                from_value = _to_float(match.group("from"))
                direction = FALL if match.group("dir").lower() == "fell" else RISE
                if to_value is not None:
                    facts.append(
                        DirectionFact(
                            value=to_value,
                            direction=direction,
                            kind="level",
                            origin=f"the evidence says it {match.group('dir').lower()} to this value",
                        )
                    )
                if from_value is not None and to_value is not None:
                    facts.append(
                        DirectionFact(
                            value=abs(from_value - to_value),
                            direction=direction,
                            kind="change",
                            origin="the size of the stated transition",
                        )
                    )
            for match in _MAGNITUDE_RE.finditer(node):
                magnitude = _to_float(match.group("num"))
                if magnitude is not None:
                    facts.append(
                        DirectionFact(
                            value=abs(magnitude),
                            direction=RISE if match.group("dir").lower() == "rise" else FALL,
                            kind="change",
                            origin="the stated size of the move",
                        )
                    )

    walk(context)
    return _drop_ambiguous(facts)


def _drop_ambiguous(facts: list[DirectionFact]) -> list[DirectionFact]:
    """Discard any value that the context describes in both directions.

    Two anomalies can share a value while moving opposite ways, and a series can
    rise by the same amount it later falls by. Nothing can be concluded from such a
    number, so it is not used to accuse the model of anything.
    """
    by_value: dict[tuple[float, str], set[str]] = {}
    for fact in facts:
        by_value.setdefault((round(fact.value, 6), fact.kind), set()).add(fact.direction)
    return [f for f in facts if len(by_value[(round(f.value, 6), f.kind)]) == 1]


def collect_transition_pairs(context: Any) -> list[tuple[float, float]]:
    """Value pairs that the evidence presents as the two ends of one move.

    Quoting both ends is itself the qualification an extreme figure needs: a reader
    shown "fell from 15,406% to 70.8%" can see the regime change happening and
    cannot mistake the peak for a present-day rate. It is the *bare* peak — "reached
    a high of 355,086%" with nothing beside it — that misleads, so only that is
    required to carry a qualifying phrase.
    """
    pairs: list[tuple[float, float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            value, previous = node.get("value"), node.get("previous_value")
            if isinstance(value, (int, float)) and isinstance(previous, (int, float)):
                pairs.append((float(previous), float(value)))
            for item in node.values():
                walk(item)
        elif isinstance(node, (list, tuple, set)):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            for match in _TRANSITION_RE.finditer(node):
                start, end = _to_float(match.group("from")), _to_float(match.group("to"))
                if start is not None and end is not None:
                    pairs.append((start, end))

    walk(context)
    return pairs


def collect_extreme_values(context: Any) -> list[float]:
    """Values in the context that must not be quoted without a qualifier."""
    found: list[float] = []

    def walk(node: Any, unit: str | None) -> None:
        if isinstance(node, dict):
            here = node.get("unit", unit)
            numeric_keys = {"value", "min_value", "max_value", "median", "lower", "upper"}
            for key, value in node.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if key in numeric_keys and is_extreme(float(value), here):
                        found.append(float(value))
                else:
                    walk(value, here)
        elif isinstance(node, (list, tuple, set)):
            for value in node:
                walk(value, unit)
        elif isinstance(node, str) and unit is None:
            # Retrieval evidence: the chunk states its own unit inline, so a bare
            # "355086%" in the text is the only signal available.
            for raw in re.findall(r"([-+]?[\d,]*\.?\d+)\s*%", node):
                value = _to_float(raw)
                if is_extreme(value, "%"):
                    found.append(float(value))  # type: ignore[arg-type]

    walk(context, None)
    return sorted(set(found))


# ── Checks ───────────────────────────────────────────────────────────────────


def _matches(a: float, b: float, tolerance: float) -> bool:
    if a == b:
        return True
    scale = max(abs(a), abs(b), 1e-9)
    if abs(a - b) <= tolerance * scale:
        return True
    # The narrator rounded a supplied value for readability.
    return any(round(b, places) == a for places in range(0, 4))


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def check_semantics(text: str, context: Any, *, tolerance: float | None = None) -> SemanticReport:
    """Read `text` against what `context` actually asserts about direction and scale."""
    tol = settings.groundedness_tolerance if tolerance is None else tolerance
    facts = collect_direction_facts(context)
    extremes = collect_extreme_values(context)
    transitions = collect_transition_pairs(context)
    if not facts and not extremes:
        return SemanticReport()

    level_facts = [f for f in facts if f.kind == "level"]
    change_facts = [f for f in facts if f.kind == "change"]

    contradictions: list[str] = []
    level_as_change: list[str] = []
    unqualified: list[str] = []

    from services.groundedness import extract_numbers  # local: avoids a cycle

    for sentence in _sentences(text):
        numbers = extract_numbers(sentence)
        lowered = sentence.lower()

        # R1 — a directional level described with the opposite vocabulary. Only
        # where the direction word governs the figure ("dropped to 21.0%"), never
        # merely where both appear in one sentence.
        for match in _DIRECTED_TO_RE.finditer(sentence):
            word = match.group("word").lower()
            if word in RISE_WORDS:
                asserted = RISE
            elif word in FALL_WORDS:
                asserted = FALL
            else:
                continue
            value = _to_float(match.group("num"))
            if value is None:
                continue
            for fact in level_facts:
                if _matches(value, fact.value, tol) and fact.direction != asserted:
                    contradictions.append(
                        f"{match.group('num')} described as a {asserted} when {fact.origin}"
                    )
                    break

        # R2 — a level presented as the size of a change.
        for match in _CHANGE_OF_RE.finditer(sentence):
            word = match.group("word").lower()
            if word not in _CHANGE_NOUNS:
                continue
            value = _to_float(match.group("num"))
            if value is None:
                continue
            if any(_matches(abs(value), f.value, tol) for f in change_facts):
                continue  # it really is a supplied change magnitude
            hit = next((f for f in level_facts if _matches(abs(value), f.value, tol)), None)
            if hit is not None:
                level_as_change.append(
                    f"{match.group('num')} is a level ({hit.origin}), not the size of a move"
                )

        # R3 — an extreme value quoted with nothing to place it in its own regime.
        if extremes and not any(term in lowered for term in QUALIFIER_TERMS):
            for literal, value in numbers:
                if not any(_matches(value, extreme, tol) for extreme in extremes):
                    continue
                # Both ends of a supplied move count as self-qualifying: the scale
                # change is visible in the sentence itself.
                partners = [
                    other
                    for start, end in transitions
                    for this, other in ((start, end), (end, start))
                    if _matches(value, this, tol)
                ]
                if any(_matches(v, partner, tol) for _, v in numbers for partner in partners):
                    continue
                unqualified.append(literal)
                break

    return SemanticReport(
        contradictions=tuple(dict.fromkeys(contradictions)),
        level_as_change=tuple(dict.fromkeys(level_as_change)),
        unqualified_extremes=tuple(dict.fromkeys(unqualified)),
        extra={"direction_facts": len(facts), "extreme_values": len(extremes)},
    )
