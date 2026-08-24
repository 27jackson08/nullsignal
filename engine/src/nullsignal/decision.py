"""The decision rule.

This module is four lines of logic and the entire thesis of NullSignal.
Everything else in the engine exists to compute its two inputs honestly.
"""
from __future__ import annotations

from . import config
from .types import DecisionState


def decide(
    risk: float,
    sufficiency: float,
    *,
    risk_threshold: float = config.RISK_THRESHOLD,
    sufficiency_threshold: float = config.SUFFICIENCY_THRESHOLD,
) -> DecisionState:
    """Map (risk, sufficiency) onto the 2x2.

    The invariant that matters: CONFIRMED_LOW requires *both* a low risk
    estimate and high sufficiency. Silence can never produce green, because
    silence drives sufficiency down and lands the zone in UNKNOWN.
    """
    risk_is_high = risk >= risk_threshold
    evidence_is_sufficient = sufficiency >= sufficiency_threshold

    if evidence_is_sufficient:
        return DecisionState.CONFIRMED_HIGH if risk_is_high else DecisionState.CONFIRMED_LOW
    return DecisionState.SUSPECTED if risk_is_high else DecisionState.UNKNOWN
