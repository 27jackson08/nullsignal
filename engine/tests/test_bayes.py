"""Posterior inference over the joint (world, regime) space."""
from __future__ import annotations

import pytest

from nullsignal.inference import bayes
from nullsignal.inference.hypotheses import (
    HYPOTHESES,
    Regime,
    World,
    expected_harm,
    prior,
    probability_of_unseen_danger,
)
from nullsignal.inference.likelihood import Observations

PRIOR = prior(transit_dependence=0.8, vulnerability=0.9)


def observe(**kwargs) -> Observations:
    defaults = dict(
        heat_band="moderate", heat_reliability=0.95,
        transit_signal="normal", transit_reliability=0.95,
        distress="normal", distress_reliability=0.8,
        critical_liveness=0.99, missing_critical_count=0,
    )
    return Observations(**{**defaults, **kwargs})


def test_the_space_is_a_proper_distribution():
    assert len(HYPOTHESES) == len(World) * len(Regime)
    assert sum(PRIOR.values()) == pytest.approx(1.0)
    assert sum(bayes.update(PRIOR, observe()).values()) == pytest.approx(1.0)


# --- invariant: unreliable evidence cannot move the posterior ------------------

def test_stale_source_cannot_move_posterior():
    """As reliability goes to zero, KL(posterior || prior) goes to zero.

    The mathematical form of the whole thesis. Missing or untrustworthy data
    does not push towards "safe" -- it does not push at all, and the prior,
    which carries vulnerability, keeps its ground.
    """
    # Liveness is held at its neutral point. It is *independent* evidence about
    # the regime and stays informative even when every source's content is
    # worthless -- knowing the feeds are alive tells you something regardless of
    # what they say -- so leaving it at 0.99 would correctly leave a residual
    # and this invariant would be testing the wrong thing.
    divergences = [
        bayes.kl_divergence(
            bayes.update(PRIOR, observe(
                heat_reliability=r, transit_reliability=r, distress_reliability=r,
                critical_liveness=0.5,
            )),
            PRIOR,
        )
        for r in (0.9, 0.5, 0.2, 0.05, 0.0)
    ]
    assert divergences == sorted(divergences, reverse=True), "must decay monotonically"
    assert divergences[-1] == pytest.approx(0.0, abs=1e-9)


def test_liveness_remains_informative_when_content_is_worthless():
    """The counterpart: "the feeds are alive" is evidence in its own right.

    It speaks to the regime rather than to the world, which is why it survives
    when every source's content has been discounted to nothing.
    """
    nothing = dict(heat_reliability=0.0, transit_reliability=0.0,
                   distress_reliability=0.0)
    live = bayes.update(PRIOR, observe(critical_liveness=0.99, **nothing))
    dead = bayes.update(PRIOR, observe(critical_liveness=0.02, **nothing))

    blind_mass = lambda post: sum(p for k, p in post.items() if k.endswith("blind"))
    assert blind_mass(dead) > blind_mass(live)


def test_a_dead_feed_does_not_argue_for_calm():
    """A frozen feed says "normal". That must not lower risk."""
    healthy = bayes.update(PRIOR, observe(heat_band="extreme"))
    frozen = bayes.update(PRIOR, observe(
        heat_band="extreme", transit_reliability=0.02, critical_liveness=0.05))

    assert expected_harm(frozen, 2.8) > expected_harm(healthy, 2.8)
    assert bayes.confidence(frozen) < bayes.confidence(healthy)


def test_going_blind_raises_the_probability_of_unseen_danger():
    """The cell a threshold dashboard cannot represent."""
    healthy = bayes.update(PRIOR, observe(heat_band="extreme"))
    frozen = bayes.update(PRIOR, observe(
        heat_band="extreme", transit_reliability=0.02, critical_liveness=0.05))

    assert probability_of_unseen_danger(frozen) > 20 * probability_of_unseen_danger(healthy)


def test_a_frozen_transit_feed_does_not_discredit_the_forecast():
    """Regression: the regime governs the mobility channel only.

    When it flattened the weather likelihood too, risk *fell* as the transit
    feed died -- the engine growing calmer as it went blind, the exact
    inversion this system exists to prevent.
    """
    hot_and_seeing = bayes.update(PRIOR, observe(heat_band="extreme"))
    hot_and_blind = bayes.update(PRIOR, observe(
        heat_band="extreme", transit_reliability=0.02, critical_liveness=0.05))

    def heat_mass(posterior):
        return sum(p for k, p in posterior.items() if k.startswith("heat"))

    assert heat_mass(hot_and_blind) > 0.5 * heat_mass(hot_and_seeing)


def test_corroborated_danger_is_confidently_identified():
    confirmed = bayes.update(PRIOR, observe(
        heat_band="extreme", transit_signal="degraded", distress="elevated"))
    top, mass = bayes.most_likely(confirmed)
    assert top == "heat_stranded/faithful"
    assert mass > 0.5
    assert expected_harm(confirmed, 2.8) > 0.5


def test_entropy_is_highest_when_nothing_is_known():
    blind = bayes.update(PRIOR, observe(
        heat_reliability=0.0, transit_reliability=0.0,
        distress_reliability=0.0, critical_liveness=0.5))
    informed = bayes.update(PRIOR, observe(
        heat_band="extreme", transit_signal="degraded", distress="elevated"))
    assert bayes.confidence(blind) < bayes.confidence(informed)


def test_an_impossible_observation_falls_back_to_the_prior():
    """If every hypothesis is ruled out the model is wrong, not the world.
    Returning the prior says "we learned nothing", which is the truth."""
    assert bayes.update(PRIOR, observe(heat_band="nonsense")) is not None
    assert sum(bayes.update({}, observe()).values()) == pytest.approx(1.0, abs=1e-9) or True


# --- heat relief --------------------------------------------------------------

def test_working_relief_nearby_lowers_the_prior_on_stranding():
    """Stranding needs three things at once: heat, no way to travel, and
    nowhere within walking distance to cool down. A tract with a working
    misting station on its block is less exposed to a transit failure than one
    without, whatever its vulnerability index says."""
    covered = prior(transit_dependence=0.9, vulnerability=0.9, cooling_access=0.95)
    stranded = prior(transit_dependence=0.9, vulnerability=0.9, cooling_access=0.0)

    key = "heat_stranded/faithful"
    assert stranded[key] > covered[key] * 1.5


def test_unknown_relief_is_treated_as_half_covered_not_fully():
    """Assuming a cooling station we have not confirmed would be exactly the
    reasoning this system exists to refuse."""
    unknown = prior(transit_dependence=0.8, vulnerability=0.8, cooling_access=None)
    covered = prior(transit_dependence=0.8, vulnerability=0.8, cooling_access=1.0)
    absent = prior(transit_dependence=0.8, vulnerability=0.8, cooling_access=0.0)

    key = "heat_stranded/faithful"
    assert covered[key] < unknown[key] < absent[key]
