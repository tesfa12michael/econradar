"""Interpretation checks — decisions #32-#34.

The cases below are not invented. The first one is the answer production actually
returned for "What happened to Brazilian policy rates in the 1990s?", and every
figure in it is real, cited, and scored 1.00 by the numeric verifier. That is the
point: this suite exists because grounded and correct turned out to be different
properties.
"""

from __future__ import annotations

import pytest

from services.groundedness import verify
from services.semantics import (
    check_semantics,
    collect_direction_facts,
    collect_transition_pairs,
    is_extreme,
)

# The corpus as `rag_index` now writes it: transitions, coverage, regime note.
BRAZIL = {
    "evidence": [
        {
            "chunk_text": (
                "Brazil (BRA) — Central bank policy rate (%). Most recent value: 15.0% in "
                "2026-06-01. Record covers 481 monthly observations from 1986-06-01 to "
                "2026-06-01, ranging from a low of 2.0% to a high of 355086.0%. Figures of "
                "this magnitude are nominal annualised rates from a hyperinflation era and "
                "are not comparable with post-stabilisation levels. Indicator code: CBPOL."
            )
        },
        {
            "chunk_text": (
                "Anomaly: Brazil (BRA) — Central bank policy rate (%) fell from 15406.0% in "
                "1994-06-01 to 70.8% in 1994-07-01, a fall of 15334.8 percentage points. "
                "Flagged as a drop, Z-score -22.6 against its trailing window. Indicator "
                "code: CBPOL."
            )
        },
        {
            "chunk_text": (
                "Anomaly: Brazil (BRA) — Central bank policy rate (%) rose from 18.0% in "
                "2002-09-01 to 21.0% in 2002-10-01, a rise of 3.0 percentage points. "
                "Flagged as a spike, Z-score 21.1 against its trailing window. Indicator "
                "code: CBPOL."
            )
        },
    ]
}

#: Verbatim from production, 2026-07-31.
PRODUCTION_FAILURE = (
    "Brazilian central bank policy rates reached a high of 355086.0% and had an anomaly of "
    "70.8% in 1994-07-01, flagged as a drop. The policy rate dropped to 21.0% in "
    "2002-10-01, but this is outside the 1990s."
)


# ── the failure that motivated all of this ───────────────────────────────────


def test_the_production_failure_is_numerically_perfect_and_still_wrong():
    """Every figure real, every figure cited, score 1.00 — and three claims false.

    This is the whole argument for a second check. If the numeric score alone
    decided, this answer would still be served today.
    """
    report = verify(PRODUCTION_FAILURE, BRAZIL)
    assert report.score == 1.0, "the numeric verifier has no objection, and never did"
    assert not report.passed, "but the answer must not be servable"
    assert not report.semantic.passed


def test_a_spike_described_as_a_fall_is_caught():
    """October 2002 is flagged `spike`, z +21.1. The answer said it dropped."""
    report = check_semantics("The policy rate dropped to 21.0% in 2002-10-01.", BRAZIL)
    assert not report.passed
    assert report.contradictions
    assert "21.0" in report.reason()


def test_a_level_presented_as_the_size_of_a_change_is_caught():
    """70.8% is where the rate landed, not how far it fell. It fell 15,334.8 points."""
    report = check_semantics("The rate saw a drop of 70.8% in 1994-07-01.", BRAZIL)
    assert not report.passed
    assert report.level_as_change


def test_a_hyperinflation_era_rate_quoted_bare_is_caught():
    report = check_semantics("Brazil's policy rate reached 355086.0% at its peak.", BRAZIL)
    assert not report.passed
    assert report.unqualified_extremes == ("355086.0",)


# ── and the honest prose it must not reject ──────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        # The qualifier carried explicitly.
        "Brazil's policy rate peaked at 355086.0%, a nominal annualised rate from the "
        "hyperinflation era, not comparable with post-stabilisation levels.",
        # Both ends of the move quoted: the scale change is visible without a phrase.
        "The policy rate fell from 15406.0% in 1994-06-01 to 70.8% in 1994-07-01, a fall "
        "of 15334.8 percentage points.",
        # The spike, described as a spike.
        "The policy rate rose to 21.0% in 2002-10-01, a rise of 3.0 percentage points.",
        # A level with no directional claim attached at all.
        "Brazil's most recent policy rate is 15.0% in 2026-06-01.",
        # Direction word present but pointing at a different, non-extreme number.
        "Rates eased through the late 1990s, reaching 15.0% by 2026-06-01.",
    ],
)
def test_correct_prose_is_left_alone(text):
    """A verifier that rejects honest answers gets turned off, so this matters."""
    report = check_semantics(text, BRAZIL)
    assert report.passed, report.reason()


#: South Africa: inflation peaks at 7.04% in 2022 (a spike) and then falls away.
#: This context caught the first draft of R1 rejecting a correct sentence, live.
SOUTH_AFRICA = {
    "unit": "%",
    "recent": [
        {"date": "2022-01-01", "value": 7.04},
        {"date": "2023-01-01", "value": 6.08},
        {"date": "2025-01-01", "value": 3.21},
    ],
    "anomalies": [
        {"date": "2022-01-01", "value": 7.04, "deviation_type": "spike", "previous_value": 4.62},
        {"date": "2004-01-01", "value": -0.69, "deviation_type": "drop", "previous_value": 5.68},
    ],
}


def test_a_peak_may_be_the_start_of_a_later_fall():
    """The regression that rejected all three providers on ZAF before it was fixed.

    7.04% is genuinely a spike *and* genuinely where a multi-year decline began.
    Sentence-level co-occurrence of "fell" and "7.04" is not a contradiction; only
    a direction word governing the figure is. Getting this wrong took narration for
    the series offline entirely, which is what over-strict verification looks like.
    """
    report = check_semantics(
        "Inflation fell from 7.04% in 2022-01-01 to 3.21% in 2025-01-01.", SOUTH_AFRICA
    )
    assert report.passed, report.reason()


def test_the_same_figure_is_still_caught_when_the_direction_governs_it():
    """The narrowing must not cost the catch: 7.04 is a spike, so easing *to* it is
    still a contradiction."""
    report = check_semantics("Inflation eased to 7.04% in 2022-01-01.", SOUTH_AFRICA)
    assert not report.passed
    assert report.contradictions


def test_a_spike_of_x_percent_is_ordinary_english_for_a_level():
    """ "a spike of 7%" means the level reached, not a 7-point move. Reading it as a
    change would reject honest prose, so only unambiguous change nouns trigger R2."""
    assert check_semantics("The series shows a spike of 7.04% in 2022-01-01.", SOUTH_AFRICA).passed


def test_a_value_the_context_describes_both_ways_accuses_nobody():
    """Two anomalies, same value, opposite directions — nothing is provable."""
    context = {
        "unit": "%",
        "anomalies": [
            {"date": "2001-01-01", "value": 12.0, "deviation_type": "spike"},
            {"date": "2009-01-01", "value": 12.0, "deviation_type": "drop"},
        ],
    }
    assert not [f for f in collect_direction_facts(context) if f.value == 12.0]
    assert check_semantics("The rate fell to 12.0%.", context).passed


def test_a_structural_break_asserts_no_direction():
    """A break is a change of regime. Claiming it rose or fell would be the same
    class of error this module exists to catch, so it contributes no fact."""
    context = {
        "unit": "%",
        "anomalies": [{"date": "1994-07-01", "value": 70.8, "deviation_type": "structural_break"}],
    }
    assert collect_direction_facts(context) == []


def test_transition_pairs_are_read_out_of_the_chunk_phrasing():
    """`rag_index` and this module agree on one sentence shape; if they drift, the
    extreme-value rule starts rejecting correct transitions."""
    pairs = collect_transition_pairs(BRAZIL)
    assert (15406.0, 70.8) in pairs
    assert (18.0, 21.0) in pairs


def test_extremeness_is_judged_only_for_percentages():
    # A GDP figure in dollars is legitimately enormous and means what it says.
    assert is_extreme(355086.0, "%")
    assert not is_extreme(355086.0, "US$")
    assert not is_extreme(15.0, "%")


def test_the_semantic_layer_can_be_switched_off(monkeypatch):
    """It rejects text the numeric check accepts, so it needs an off switch that
    does not require a deploy to reach."""
    from config import settings

    monkeypatch.setattr(settings, "semantic_checks_enabled", False)
    assert verify(PRODUCTION_FAILURE, BRAZIL).passed
