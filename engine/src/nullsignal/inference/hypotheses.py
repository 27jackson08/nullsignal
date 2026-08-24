"""The hypothesis space.

A hypothesis here is a *pair*: what is happening in the world, and whether our
instruments can see it.

    hypothesis = (world state, observation regime)

Splitting them this way is the whole point. A conventional monitoring system
reasons only over world states, so it has no way to represent "the situation
may be bad and my feeds may be lying about it" -- and therefore can never
conclude that it might be blind. Here that cell exists explicitly:
(HEAT_STRANDED, BLIND) is a hypothesis the engine can raise probability on.

Keeping the regime separate rather than folding "sensor failure" in as another
world state also keeps the space orthogonal, so the posterior stays a genuine
probability distribution over mutually exclusive alternatives.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import product

from .. import config


class World(StrEnum):
    """What is actually happening on the ground."""

    NORMAL = "normal"                  # nothing unusual
    HEAT = "heat"                      # dangerous heat, mobility intact
    HEAT_STRANDED = "heat_stranded"    # dangerous heat and transit has failed
    LOCAL_FAULT = "local_fault"        # localised infrastructure problem


class Regime(StrEnum):
    """Whether we can actually see the mobility situation.

    Scoped to the mobility channel on purpose. The regime exists to capture a
    failure mode that per-source reliability cannot: a frozen realtime feed
    does not emit noise, it replays its last good state, so it reports healthy
    service *specifically when* service has stopped. That directional bias is a
    property of replay-style feeds, not of every source, and modelling it
    globally made the engine grow calmer as it went blind.

    Ordinary untrustworthiness -- a stale forecast, a tract that rarely reports
    -- is handled where it belongs, in each source's own reliability discount.
    """

    FAITHFUL = "faithful"   # the realtime mobility picture reflects reality
    BLIND = "blind"         # it is stale, frozen or absent


@dataclass(frozen=True, slots=True)
class Hypothesis:
    world: World
    regime: Regime

    @property
    def key(self) -> str:
        return f"{self.world}/{self.regime}"

    @property
    def is_harmful(self) -> bool:
        return self.world in HARM_BY_WORLD and HARM_BY_WORLD[self.world] > 0

    @property
    def is_unseen_danger(self) -> bool:
        """The cell a threshold dashboard cannot represent: something is wrong
        *and* the instruments are not showing it."""
        return self.regime is Regime.BLIND and HARM_BY_WORLD[self.world] > 0


HYPOTHESES: tuple[Hypothesis, ...] = tuple(
    Hypothesis(world, regime) for world, regime in product(World, Regime)
)

# Expected harm per capita if a world state goes unaddressed, on 0..1. Heat with
# no way to leave is the scenario this system was built around: people who
# cannot reach a cooling centre are the ones who die in heatwaves.
HARM_BY_WORLD: dict[World, float] = {
    World.NORMAL: 0.0,
    World.HEAT: 0.55,
    World.HEAT_STRANDED: 1.0,
    World.LOCAL_FAULT: 0.30,
}
# Calibration note: at 0.35, even a tract *confidently* identified as being in
# dangerous heat, at maximum vulnerability, scored 0.35 risk -- below the 0.45
# threshold -- and came back CONFIRMED_LOW. The scoreboard caught it: the engine
# was falsely reassuring about half of a 104F heatwave. At 0.55 a vulnerable
# tract in confirmed heat clears the threshold and a robust one does not, which
# is the equity mechanism doing its job rather than a blanket alarm.

# Base rates before any of today's evidence. Deliberately climatological rather
# than derived from the current forecast: today's heat reading is *evidence*,
# and letting it set the prior as well would count it twice.
BASE_WORLD_PRIOR: dict[World, float] = {
    World.NORMAL: 0.80,
    World.HEAT: 0.10,
    World.HEAT_STRANDED: 0.02,
    World.LOCAL_FAULT: 0.08,
}

# Prior odds that our instruments are not faithful, before the liveness
# detectors have said anything.
BASE_BLIND_PRIOR = 0.05


def prior(
    *,
    transit_dependence: float | None,
    vulnerability: float | None,
    blind_prior: float = BASE_BLIND_PRIOR,
) -> dict[str, float]:
    """Prior over the joint space for one zone.

    The stranded case is scaled by how much this tract depends on transit: a
    neighbourhood where nearly everyone drives is not one where a subway
    failure strands people. Vulnerability raises the prior on hazard states
    generally, because the same weather is a different event for a tract full
    of elderly residents without air conditioning.
    """
    dependence = 0.5 if transit_dependence is None else transit_dependence
    exposure = 0.5 if vulnerability is None else vulnerability

    world = dict(BASE_WORLD_PRIOR)
    world[World.HEAT_STRANDED] *= 0.4 + 2.2 * dependence
    world[World.HEAT] *= 0.6 + 0.8 * exposure
    world = _normalise(world)

    return _normalise({
        Hypothesis(w, r).key: p * (blind_prior if r is Regime.BLIND else 1 - blind_prior)
        for w, p in world.items()
        for r in Regime
    })


def scaled_harm(world: World, zone_multiplier: float = 1.0) -> float:
    """Harm from a world state for this zone, on a 0..1 scale.

    The single definition of harm. `expected_harm` and the decision utilities
    both route through here: when they each normalised differently, a tract
    could come out CONFIRMED_LOW while the recommended action was "dispatch
    crews" -- a verdict and a decision computed on incompatible scales.
    """
    ceiling = config.VULNERABILITY_MULTIPLIER_RANGE[1]
    return min(1.0, HARM_BY_WORLD[world] * zone_multiplier / ceiling)


def expected_harm(posterior: dict[str, float], zone_multiplier: float = 1.0) -> float:
    """Probability-weighted harm, scaled by who is exposed.

    Note what is absent: any term for how *confident* we are. Risk and
    sufficiency are separate axes, and mixing them here would rebuild the
    single green-to-red ramp this product exists to replace.
    """
    return min(1.0, sum(
        probability * scaled_harm(_parse(key).world, zone_multiplier)
        for key, probability in posterior.items()
    ))


def probability_of_unseen_danger(posterior: dict[str, float]) -> float:
    """How much of the posterior sits in cells where something is wrong and the
    instruments are not showing it."""
    return sum(
        probability for key, probability in posterior.items()
        if _parse(key).is_unseen_danger
    )


def _parse(key: str) -> Hypothesis:
    world, regime = key.split("/")
    return Hypothesis(World(world), Regime(regime))


def _normalise(weights: dict) -> dict:
    total = sum(weights.values())
    if total <= 0:
        uniform = 1.0 / len(weights)
        return {k: uniform for k in weights}
    return {k: v / total for k, v in weights.items()}
