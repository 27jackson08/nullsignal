"""Value of information: what to check next, and why."""
from __future__ import annotations

import pytest

from nullsignal.inference import bayes
from nullsignal.inference.hypotheses import expected_harm, prior
from nullsignal.inference.likelihood import Observations
from nullsignal.voi import evpi
from nullsignal.voi.actions import ACTIONS, DECISION_COST, Decision

FROZEN_FEED_IN_A_HEATWAVE = Observations(
    heat_band="extreme", heat_reliability=0.97,
    transit_signal="normal", transit_reliability=0.02,
    distress="low", distress_reliability=0.8,
    critical_liveness=0.05, missing_critical_count=0,
)


def posterior_for(*, transit_dependence=0.8, vulnerability=0.9):
    return bayes.update(
        prior(transit_dependence=transit_dependence, vulnerability=vulnerability),
        FROZEN_FEED_IN_A_HEATWAVE,
    )


# --- invariant: equity is structural -----------------------------------------

def test_equity_monotonicity():
    """Evidence held constant, a more vulnerable tract outranks a robust one.

    Measured on `unresolved_harm`, which is the queue key -- not on VOI. VOI is
    deliberately *not* monotone in stakes and cannot be: information is worth
    most near a decision boundary and nothing at all once one response
    dominates whatever the answer turns out to be. Ranking zones by VOI would
    put the most clear-cut emergencies last.

    If this ever fails, the fairness claim is decoration.
    """
    posterior = posterior_for()
    values = [
        evpi.unresolved_harm(posterior, sufficiency=0.4, harm_scale=scale)
        for scale in (1.0, 1.5, 2.0, 2.5, 3.0)
    ]
    assert values == sorted(values), f"expected monotone increase, got {values}"
    assert values[-1] > values[0]


def test_doubt_also_raises_a_zone_up_the_queue():
    """The other half: the same believed harm, less firmly established, is more
    urgent to resolve."""
    posterior = posterior_for()
    values = [
        evpi.unresolved_harm(posterior, sufficiency=s, harm_scale=2.5)
        for s in (0.9, 0.7, 0.5, 0.3)
    ]
    assert values == sorted(values), f"expected monotone increase, got {values}"


def test_value_of_information_is_not_monotone_in_stakes():
    """Documents the shape of VOI rather than wishing it away.

    Asserted explicitly so nobody later "fixes" the queue by ranking zones on
    VOI: past the point where crews are going regardless, another check changes
    nothing and is correctly worth zero.
    """
    posterior = posterior_for()
    values = [evpi.rank(posterior, harm_scale=s)[0].value
              for s in (1.0, 1.5, 2.0, 2.5, 3.0)]
    assert values != sorted(values), "VOI should peak near a decision boundary"


def test_the_same_evidence_in_a_fragile_tract_outranks_a_robust_one():
    """End to end, through the priors as well as the harm scale."""
    fragile = posterior_for(transit_dependence=0.9, vulnerability=0.95)
    robust = posterior_for(transit_dependence=0.1, vulnerability=0.1)

    assert expected_harm(fragile, 2.9) > expected_harm(robust, 1.1)
    assert evpi.unresolved_harm(fragile, 0.4, 2.9) > \
           evpi.unresolved_harm(robust, 0.4, 1.1)


# --- the ranking behaves like decision theory ---------------------------------

def test_information_that_cannot_change_the_decision_is_worth_nothing():
    """EVPI is about decisions, not curiosity. If we would act identically
    whatever the answer, the check earns a zero and should not be ordered."""
    certain = {"normal/faithful": 1.0}
    for ranked in evpi.rank(certain, harm_scale=1.0):
        assert ranked.value == pytest.approx(0.0)


def test_every_action_is_scored_and_ordered_by_value_per_cost():
    ranked = evpi.rank(posterior_for(), harm_scale=2.8)
    assert len(ranked) == len(ACTIONS)
    ratios = [r.value_per_cost for r in ranked]
    assert ratios == sorted(ratios, reverse=True)


def test_a_check_that_settles_whether_trains_run_has_value_in_a_blind_heatwave():
    """Regression: these checks once scored exactly zero for everyone.

    They were modelled as resolving only the *regime* -- whether our feed could
    be trusted -- when what a call to transit control actually settles is
    whether trains are moving, which discriminates the harmful world directly.
    """
    ranked = {r.key: r for r in evpi.rank(posterior_for(), harm_scale=2.8)}
    assert ranked["call_transit_ops"].value > 0
    assert ranked["call_transit_ops"].value_per_cost == max(
        r.value_per_cost for r in evpi.rank(posterior_for(), harm_scale=2.8)
    )


def test_a_less_reliable_check_of_the_same_question_is_worth_less():
    """Both calls settle whether trains are running; one settles it better.

    Asserted as an ordering rather than an exact figure, because the absolute
    value moves with likelihood calibration while the ranking should not: a
    source whose weakness is that it tends to agree with the feed it is meant
    to check cannot be worth more than picking up the phone.
    """
    ranked = {r.key: r for r in evpi.rank(posterior_for(), harm_scale=2.8)}
    assert ranked["call_transit_ops"].value > ranked["alternate_transit_feed"].value


# --- decisions stay coherent with the verdict ---------------------------------

def test_decision_thresholds_track_the_risk_thresholds():
    """A tract the matrix calls low must never be told to send crews.

    Regression: harm was normalised in the verdict but not in the utilities, so
    tracts came out "confirmed low" with "dispatch" beside them -- a verdict
    and an action computed on incompatible scales.
    """
    from nullsignal import config

    calm = {"normal/faithful": 0.97, "heat/faithful": 0.03}
    decision, _ = evpi.best_decision(calm, harm_scale=3.0)
    assert decision is Decision.HOLD
    assert expected_harm(calm, 3.0) < config.RISK_THRESHOLD

    dire = {"heat_stranded/faithful": 0.9, "heat/faithful": 0.1}
    decision, _ = evpi.best_decision(dire, harm_scale=3.0)
    assert decision is Decision.DISPATCH
    assert expected_harm(dire, 3.0) >= config.RISK_THRESHOLD


def test_doing_nothing_is_free_and_dispatch_is_not():
    assert DECISION_COST[Decision.HOLD] == 0.0
    assert DECISION_COST[Decision.ADVISORY] < DECISION_COST[Decision.DISPATCH]
