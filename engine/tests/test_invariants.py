"""The six invariants that define NullSignal.

These are the product specification. If they all pass, the system does what it
claims. Tests for components not yet built are skipped with the day they
unlock, so the suite doubles as a build progress meter rather than quietly
reporting green on work that has not happened.
"""
from __future__ import annotations

import pytest

from nullsignal import config
from nullsignal.decision import decide
from nullsignal.eval import baseline
from nullsignal.inference import engine
from nullsignal.types import DecisionState, Reliability

from helpers import make_evidence, make_zone


# --- 1. Silence never confirms safe -------------------------------------------

def test_silence_never_confirms_safe():
    """A zone with no evidence must be UNKNOWN, never CONFIRMED_LOW.

    This is the entire thesis. If it ever fails, the system is a conventional
    dashboard wearing a different colour scheme.
    """
    silent = make_evidence(
        sources={name: Reliability.absent() for name in
                 ("311", "nws", "gtfs_rt", "cdc_svi")},
        heat_index_f=None,
        report_count=0,
        latest_report_at=None,
        transit_feed_age_seconds=None,
    )
    assessment = engine.assess(silent)

    assert assessment.state is DecisionState.UNKNOWN
    assert not assessment.state.is_reassuring


def test_baseline_by_contrast_calls_silence_safe():
    """Establishes the gap NullSignal exists to close.

    The baseline is not misconfigured -- it is structurally incapable of saying
    "I don't know", so silence resolves to safe.
    """
    silent = make_evidence(
        sources={name: Reliability.absent() for name in
                 ("311", "nws", "gtfs_rt", "cdc_svi")},
        heat_index_f=None, report_count=0, latest_report_at=None,
        transit_feed_age_seconds=None,
    )
    assert baseline.assess(silent).state.is_reassuring


def test_missing_critical_source_caps_sufficiency():
    """Losing a decision-critical source alone is enough to forfeit a safe call,
    however healthy every other feed looks."""
    for critical in config.CRITICAL_SOURCES:
        sources = {n: Reliability() for n in ("311", "nws", "gtfs_rt", "cdc_svi")}
        sources[critical] = Reliability.absent()
        assessment = engine.assess(make_evidence(sources=sources, heat_index_f=70.0))
        assert assessment.state is DecisionState.UNKNOWN, critical
        assert assessment.sufficiency.score <= config.CRITICAL_GAP_CEILING


# --- 2. Contradictions widen rather than average ------------------------------

# Landed on day 3. Lives in test_contradictions.py:
#   test_contradiction_widens_uncertainty_and_leaves_the_risk_estimate_alone


# --- 3. Unreliable evidence cannot move the posterior -------------------------

# Landed on day 4. Lives in test_bayes.py::test_stale_source_cannot_move_posterior


def test_stale_critical_source_lowers_sufficiency():
    """Day 1 precursor: decision-critical evidence going stale must cost us."""
    fresh_sources = {n: Reliability() for n in ("311", "nws", "gtfs_rt", "cdc_svi")}
    stale_sources = dict(fresh_sources)
    stale_sources["nws"] = Reliability(freshness=0.1)

    fresh = engine.assess(make_evidence(sources=fresh_sources))
    stale = engine.assess(make_evidence(sources=stale_sources))
    assert stale.sufficiency.score < fresh.sufficiency.score


def test_quiet_reports_do_not_read_as_stale_evidence():
    """A tract simply not complaining lately is not a dead feed.

    Regression guard: staleness was once the worst raw age across all sources
    against one global horizon. Because 311 has no per-tract heartbeat and goes
    quiet for days routinely, that drove freshness to zero almost everywhere --
    conflating "nobody reported anything" with "the feed is broken", which are
    the two claims this system exists to keep apart.
    """
    from datetime import timedelta
    from helpers import NOW

    chatty = engine.assess(make_evidence(latest_report_at=NOW))
    quiet = engine.assess(make_evidence(latest_report_at=NOW - timedelta(days=6)))
    assert quiet.sufficiency.staleness == chatty.sufficiency.staleness


# --- 4. Equity is structural --------------------------------------------------

# Landed on day 4. Lives in test_voi.py::test_equity_monotonicity -- measured on
# unresolved harm rather than VOI, which is not monotone in stakes. See the note
# there.


def test_vulnerability_multiplier_is_monotonic():
    """Day 1 precursor: the multiplier VOI will consume already rises with SVI."""
    low = make_zone(svi_overall=0.05).vulnerability_multiplier
    high = make_zone(svi_overall=0.95).vulnerability_multiplier
    assert high > low
    assert config.VULNERABILITY_MULTIPLIER_RANGE[0] <= low
    assert high <= config.VULNERABILITY_MULTIPLIER_RANGE[1]


# --- 5. It beats the baseline where it counts ---------------------------------

@pytest.mark.skip(reason="unlocks day 5: scenario engine and scoreboard")
def test_silent_failure_beats_baseline():
    """Detection lead time over the baseline must be positive."""


# --- 6. The explanation layer cannot invent numbers ---------------------------

@pytest.mark.skip(reason="unlocks day 7: LLM explanation layer")
def test_llm_emits_no_unsupported_numbers():
    """Every numeric token in generated prose must trace to the evidence packet."""


# --- The 2x2 itself -----------------------------------------------------------

@pytest.mark.parametrize(
    ("risk", "sufficiency", "expected"),
    [
        (0.1, 0.9, DecisionState.CONFIRMED_LOW),
        (0.9, 0.9, DecisionState.CONFIRMED_HIGH),
        (0.1, 0.1, DecisionState.UNKNOWN),
        (0.9, 0.1, DecisionState.SUSPECTED),
    ],
)
def test_decision_matrix_covers_all_four_cells(risk, sufficiency, expected):
    assert decide(risk, sufficiency) is expected


def test_only_one_state_reassures():
    reassuring = [s for s in DecisionState if s.is_reassuring]
    assert reassuring == [DecisionState.CONFIRMED_LOW]


def test_unknown_vulnerability_does_not_deprioritise_a_zone():
    """A tract whose SVI is suppressed must not be treated as low-vulnerability.

    Defaulting to the floor would rank the least-documented tracts last for
    verification, which is the exact failure this system exists to prevent.
    """
    low, high = config.VULNERABILITY_MULTIPLIER_RANGE
    unknown = make_zone(svi_overall=None).vulnerability_multiplier
    least_vulnerable = make_zone(svi_overall=0.0).vulnerability_multiplier

    assert unknown > least_vulnerable
    assert low < unknown < high
    assert not make_zone(svi_overall=None).vulnerability_is_known


# --- silent failure changes our verdict, and only ours ------------------------

def test_frozen_feed_changes_our_verdict_but_not_the_baseline():
    """A feed that is up and frozen must move us and cannot move a threshold.

    This is the day-5 scoreboard in miniature. The baseline sees HTTP 200 and a
    plausible payload, so its inputs are unchanged and its output is identical
    by construction -- not because it is badly tuned, but because a threshold
    on values cannot represent a doubt about whether the values are real.
    """
    transit_dependent = make_zone(pct_no_vehicle=0.8)
    healthy = {n: Reliability() for n in ("311", "nws", "gtfs_rt", "cdc_svi")}
    frozen = {**healthy, "gtfs_rt": Reliability(liveness=0.0)}

    before = make_evidence(zone=transit_dependent, sources=healthy, heat_index_f=70.0)
    after = make_evidence(zone=transit_dependent, sources=frozen, heat_index_f=70.0)

    assert engine.assess(before).state is DecisionState.CONFIRMED_LOW
    assert engine.assess(after).state is DecisionState.UNKNOWN

    # The dashboard cannot tell the two situations apart.
    assert baseline.assess(before).state is baseline.assess(after).state


def test_a_frozen_feed_is_ignored_where_nobody_depends_on_it():
    """The same frozen feed, in a tract where almost everyone drives, is not a
    decision-critical gap. Flagging it anyway would bury the tracts that matter."""
    car_dependent = make_zone(pct_no_vehicle=0.05)
    frozen = {n: Reliability() for n in ("311", "nws", "gtfs_rt", "cdc_svi")}
    frozen["gtfs_rt"] = Reliability(liveness=0.0)

    evidence = make_evidence(zone=car_dependent, sources=frozen, heat_index_f=70.0)
    assert "gtfs_rt" not in evidence.missing_critical_sources
    assert engine.assess(evidence).state is DecisionState.CONFIRMED_LOW
