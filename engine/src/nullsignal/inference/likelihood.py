"""Likelihoods: how probable each observation is under each hypothesis.

Two ideas carry this module.

**A blind regime makes the instruments agree with nothing in particular.** A
frozen transit feed does not emit noise; it emits the last good state, which
looks exactly like healthy service. So P(see "normal" | transit has failed,
regime blind) is *high*, not low. That single asymmetry is what lets the
posterior conclude "the feed says normal, and that is precisely what it would
say if it had died" -- a conclusion no threshold on the feed's own values can
reach.

**Unreliable evidence cannot move the posterior.** Each source's likelihood is
mixed towards uniform in proportion to how much that source is worth here:

    P(obs | H) = reliability * P_table(obs | H) + (1 - reliability) * uniform

As reliability goes to zero the likelihood goes flat, so the observation stops
discriminating between hypotheses altogether. Missing data therefore does not
push towards "safe" -- it does not push at all, and the prior, which carries
vulnerability, keeps its ground.
"""
from __future__ import annotations

from dataclasses import dataclass

from .hypotheses import Hypothesis, Regime, World

# --- observation vocabularies -------------------------------------------------

HEAT_BANDS = ("low", "moderate", "high", "extreme")
TRANSIT_SIGNALS = ("normal", "degraded", "absent")
DISTRESS_LEVELS = ("low", "normal", "elevated")


@dataclass(frozen=True, slots=True)
class Observations:
    """Everything observed about one zone at one tick, already lifted into
    claim vocabulary, with the reliability of each source alongside."""

    heat_band: str | None
    heat_reliability: float

    transit_signal: str | None
    transit_reliability: float

    distress: str | None
    distress_reliability: float

    # Direct evidence about the regime: how live the decision-critical feeds
    # look, and how many of them are missing outright.
    critical_liveness: float
    missing_critical_count: int


# --- likelihood tables --------------------------------------------------------

# P(heat band | world), when the weather feed is faithful. Heat is independent
# of infrastructure faults, so LOCAL_FAULT mirrors NORMAL.
# HEAT_STRANDED is *defined* as dangerous heat plus a transit failure, so mild
# weather should nearly rule it out. Before this was sharpened, a routine
# service alert on an 82F day pushed "people are stranded" to the top of the
# posterior while the verdict still read "confirmed low" -- a pairing that
# would rightly cost an operator's trust in the whole instrument.
_HEAT_GIVEN_WORLD: dict[World, tuple[float, ...]] = {
    World.NORMAL:        (0.45, 0.40, 0.13, 0.02),
    World.HEAT:          (0.02, 0.18, 0.50, 0.30),
    World.HEAT_STRANDED: (0.005, 0.045, 0.50, 0.45),
    World.LOCAL_FAULT:   (0.45, 0.40, 0.13, 0.02),
}

# P(transit signal | world), faithful regime.
_TRANSIT_GIVEN_WORLD: dict[World, tuple[float, ...]] = {
    World.NORMAL:        (0.93, 0.06, 0.01),
    World.HEAT:          (0.90, 0.09, 0.01),
    World.HEAT_STRANDED: (0.05, 0.90, 0.05),
    # A localised fault -- a signal failure, a water main, a power cut -- is the
    # ordinary explanation for degraded service on a mild day. Without this the
    # world space had no home for "transit disrupted, weather fine", and the
    # posterior was forced to reach for the mass-casualty hypothesis to explain
    # a routine alert.
    World.LOCAL_FAULT:   (0.35, 0.60, 0.05),
}

# P(transit signal | any world), blind regime.
#
# The load-bearing row. A frozen feed replays its last good state, so it reads
# "normal" whatever is really happening. Under this regime the transit signal
# carries almost no information about the world -- which is exactly why a
# dashboard reading it at face value stays calm through a failure.
_TRANSIT_GIVEN_BLIND: tuple[float, ...] = (0.78, 0.04, 0.18)

# P(distress | world). Note how weakly "low" discriminates: 0.25 under
# stranding against 0.18 under normal conditions. Quiet is only slightly more
# surprising in a crisis than out of one.
#
# That is deliberate, and it is the thesis stated as a number. An earlier table
# put P(low | stranded) at 0.08 -- asserting that stranded people almost
# certainly complain -- and a scenario where reporting was suppressed while
# conditions worsened drove NullSignal to *confidently* call half the affected
# tracts safe. The suppression worked, because the model had been told silence
# means safety.
#
# People stranded in a heatwave are frequently the least able to call: elderly,
# isolated, without a working phone, without English, or long past expecting a
# response. An engine built to notice that cannot also assume the opposite in
# its likelihoods. Elevated reporting remains strong evidence; its absence is
# close to none.
_DISTRESS_GIVEN_WORLD: dict[World, tuple[float, ...]] = {
    World.NORMAL:        (0.18, 0.72, 0.10),
    World.HEAT:          (0.20, 0.48, 0.32),
    World.HEAT_STRANDED: (0.25, 0.35, 0.40),
    World.LOCAL_FAULT:   (0.20, 0.45, 0.35),
}

# How sharply a missing decision-critical source argues for the blind regime.
MISSING_SOURCE_ODDS = 6.0


def likelihood(observations: Observations, hypothesis: Hypothesis) -> float:
    """P(all observations | hypothesis). Sources treated as conditionally
    independent given the hypothesis, which is what the joint (world, regime)
    factoring buys us: the regime absorbs the correlation that would otherwise
    exist between feeds failing together."""
    blind = hypothesis.regime is Regime.BLIND

    # Weather is *not* flattened by the regime. The regime governs the
    # mobility channel, where the replay-last-good failure mode lives; a frozen
    # subway feed tells us nothing about whether the forecast is sound. Letting
    # it flatten the heat likelihood made risk *fall* when the transit feed
    # died -- the engine growing calmer as it went blind, which is the exact
    # inversion this whole system exists to prevent. Per-source trust is
    # already carried by each source's own reliability discount.
    heat = _categorical(
        observations.heat_band, HEAT_BANDS,
        _HEAT_GIVEN_WORLD[hypothesis.world],
        observations.heat_reliability,
        flatten=False,
    )
    transit = _categorical(
        observations.transit_signal, TRANSIT_SIGNALS,
        _TRANSIT_GIVEN_BLIND if blind else _TRANSIT_GIVEN_WORLD[hypothesis.world],
        observations.transit_reliability,
        flatten=False,   # the blind row is already the right distribution
    )
    # Likewise 311: how much a tract's reporting is worth is already carried
    # by `distress_reliability`, which is its propensity-derived evidential
    # weight, and does not depend on whether the subway feed is alive.
    distress = _categorical(
        observations.distress, DISTRESS_LEVELS,
        _DISTRESS_GIVEN_WORLD[hypothesis.world],
        observations.distress_reliability,
        flatten=False,
    )
    return heat * transit * distress * _regime_evidence(observations, blind)


def _regime_evidence(observations: Observations, blind: bool) -> float:
    """Direct evidence about whether the instruments are faithful.

    The liveness detectors speak to this and nothing else, so they enter as
    their own factor rather than being smeared across the world states.
    """
    live = _clamp(observations.critical_liveness, 0.02, 0.98)
    weight = live if not blind else (1.0 - live)

    if observations.missing_critical_count > 0:
        odds = MISSING_SOURCE_ODDS ** observations.missing_critical_count
        weight *= odds if blind else 1.0

    return weight


def _categorical(
    observed: str | None,
    vocabulary: tuple[str, ...],
    table: tuple[float, ...],
    reliability: float,
    *,
    flatten: bool,
) -> float:
    """One source's contribution, discounted towards uniform by reliability.

    An unobserved value contributes 1.0 rather than 0: we did not see it, which
    is not the same as having seen it fail to happen.
    """
    if observed is None or observed not in vocabulary:
        return 1.0

    uniform = 1.0 / len(vocabulary)
    base = uniform if flatten else table[vocabulary.index(observed)]
    trust = _clamp(reliability, 0.0, 1.0)
    return trust * base + (1.0 - trust) * uniform


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
