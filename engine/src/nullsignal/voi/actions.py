"""Verification actions and the operational decisions they inform."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .. import config
from ..inference.hypotheses import World


class Decision(StrEnum):
    """What an operator does about a zone."""

    HOLD = "hold"            # take no action
    ADVISORY = "advisory"    # outreach, warnings, open a cooling centre
    DISPATCH = "dispatch"    # send crews, wellness checks, shuttle service


# Share of a world's harm each response averts is defined just below; the
# breakeven points are derived from it rather than hand-set, so the recommended
# action and the 2x2 verdict cannot drift apart.
#
# Dispatch becomes optimal at exactly the risk level where the matrix stops
# calling a tract low. Otherwise a tract reads "confirmed low" while the advice
# beside it says "send crews" -- two numbers computed on different scales,
# which is precisely the kind of quiet inconsistency this project exists to
# surface rather than commit.
#
# Advisories break even earlier on purpose: they are cheap, and warning people
# before a situation is confirmed is the whole point of an advisory.
DISPATCH_BREAKEVEN = config.RISK_THRESHOLD
ADVISORY_BREAKEVEN = config.RISK_THRESHOLD * 0.45

# Scarcity is what these encode. Crews sent to one tract are unavailable to
# another, so a model where dispatch is nearly always optimal is not cautious,
# it is useless as decision support.

# Share of a world's harm that each decision actually averts. Advisories help
# people who can act on them; dispatch reaches those who cannot, which is why
# it dominates in the stranded case.
MITIGATION: dict[Decision, dict[World, float]] = {
    Decision.HOLD:     {w: 0.0 for w in World},
    Decision.ADVISORY: {World.NORMAL: 0.0, World.HEAT: 0.55,
                        World.HEAT_STRANDED: 0.20, World.LOCAL_FAULT: 0.25},
    Decision.DISPATCH: {World.NORMAL: 0.0, World.HEAT: 0.80,
                        World.HEAT_STRANDED: 0.85, World.LOCAL_FAULT: 0.75},
}

# The stranded case is what these responses are sized against, so its
# mitigation sets the exchange rate between harm and effort.
_REFERENCE_WORLD = World.HEAT_STRANDED

DECISION_COST: dict[Decision, float] = {
    Decision.HOLD: 0.0,
    Decision.ADVISORY: round(
        MITIGATION[Decision.ADVISORY][_REFERENCE_WORLD] * ADVISORY_BREAKEVEN, 4),
    Decision.DISPATCH: round(
        MITIGATION[Decision.DISPATCH][_REFERENCE_WORLD] * DISPATCH_BREAKEVEN, 4),
}


# What a check actually settles. A check does not usually resolve the whole
# hypothesis; it partitions it. Calling transit control does not tell you
# whether it is a heatwave -- it tells you whether trains are moving.
class Resolves(StrEnum):
    WORLD = "world"          # sees the situation whole
    REGIME = "regime"        # settles only whether our feed was trustworthy
    MOBILITY = "mobility"    # settles whether transit is actually running


# Whether transit is running, per world state.
MOBILITY_BY_WORLD: dict[World, str] = {
    World.NORMAL: "running",
    World.HEAT: "running",
    World.HEAT_STRANDED: "disrupted",
    # A local fault does disrupt service -- that is usually what a routine
    # service alert is -- so a call to transit control cannot by itself tell a
    # signal problem apart from a stranding event.
    World.LOCAL_FAULT: "disrupted",
}
MOBILITY_OUTCOMES = ("running", "disrupted")


@dataclass(frozen=True, slots=True)
class VerificationAction:
    """A check that would tell us something we do not currently know."""

    key: str
    label: str
    cost: float               # operational cost on the same 0..1 scale
    resolves: Resolves
    accuracy: float           # probability the check reads correctly
    latency_minutes: int
    detail: str = ""


# The action set is small and concrete on purpose: these are things a duty
# officer can actually order in the next hour.
ACTIONS: tuple[VerificationAction, ...] = (
    VerificationAction(
        key="call_transit_ops",
        label="Call transit operations control",
        cost=0.01, resolves=Resolves.MOBILITY, accuracy=0.95, latency_minutes=10,
        detail="a human on the line settles whether service is actually running",
    ),
    VerificationAction(
        key="alternate_transit_feed",
        label="Cross-check an alternate transit source",
        cost=0.004, resolves=Resolves.MOBILITY, accuracy=0.80, latency_minutes=3,
        detail="independent feed, cheap but agrees with the primary by default",
    ),
    VerificationAction(
        key="field_inspection",
        label="Send an inspector to the tract",
        cost=0.09, resolves=Resolves.WORLD, accuracy=0.93, latency_minutes=55,
        detail="slow and expensive, but sees the situation directly",
    ),
    VerificationAction(
        key="resident_callback",
        label="Call back recent 311 callers",
        cost=0.02, resolves=Resolves.WORLD, accuracy=0.70, latency_minutes=25,
        detail="reaches people who already spoke up, so it misses the silent",
    ),
    VerificationAction(
        key="cooling_centre_check",
        label="Confirm cooling centre is open and reachable",
        cost=0.015, resolves=Resolves.WORLD, accuracy=0.75, latency_minutes=20,
        detail="confirms whether the mitigation we would order actually exists",
    ),
)
