"""Core domain types. All immutable."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import prod

from . import config


class DecisionState(StrEnum):
    """The 2x2. UNKNOWN and SUSPECTED are the cells a conventional system
    cannot represent, and the reason this project exists."""

    UNKNOWN = "UNKNOWN"                  # low risk estimate, low sufficiency
    CONFIRMED_LOW = "CONFIRMED_LOW"      # low risk estimate, high sufficiency
    SUSPECTED = "SUSPECTED"              # high risk estimate, low sufficiency
    CONFIRMED_HIGH = "CONFIRMED_HIGH"    # high risk estimate, high sufficiency

    @property
    def is_reassuring(self) -> bool:
        """Only one state tells an operator a place is fine."""
        return self is DecisionState.CONFIRMED_LOW


@dataclass(frozen=True, slots=True)
class Zone:
    """A census tract, joined to its CDC SVI vulnerability profile."""

    geoid: str
    name: str
    borough: str
    population: int
    svi_overall: float          # RPL_THEMES percentile, 0-1
    pct_no_vehicle: float       # stranded by a transit failure
    pct_age_65_plus: float      # heat-vulnerable
    pct_limited_english: float  # strong negative predictor of 311 reporting
    pct_poverty: float
    pct_minority: float

    @property
    def vulnerability_is_known(self) -> bool:
        """CDC suppresses SVI estimates for small-population tracts, so for
        some zones we do not know who lives there or how exposed they are."""
        return self.svi_overall is not None

    @property
    def vulnerability_multiplier(self) -> float:
        """Scales expected harm. This is where equity enters the arithmetic
        rather than the copy.

        When SVI is suppressed the multiplier falls back to the midpoint of the
        range, never the floor. Treating unknown vulnerability as low
        vulnerability would quietly deprioritise precisely the tracts the data
        says least about -- the inversion this whole system exists to prevent.
        The midpoint is a placeholder for the point estimate only; the fact that
        it is unknown is carried separately, by sufficiency, which caps these
        zones below the threshold for any safe call.
        """
        low, high = config.VULNERABILITY_MULTIPLIER_RANGE
        if self.svi_overall is None:
            return (low + high) / 2.0
        return low + (high - low) * self.svi_overall


@dataclass(frozen=True, slots=True)
class Reliability:
    """How much a single source's word is worth for one zone at one time."""

    freshness: float = 1.0   # exp(-dt / tau)
    coverage: float = 1.0    # observable fraction of the zone
    liveness: float = 1.0    # 0 when the feed is up but semantically dead
    accuracy: float = config.MAX_SOURCE_ACCURACY

    @property
    def score(self) -> float:
        return prod((self.freshness, self.coverage, self.liveness, self.accuracy))

    @classmethod
    def absent(cls) -> Reliability:
        """No evidence at all -- not to be confused with evidence of absence."""
        return cls(freshness=0.0, coverage=0.0, liveness=0.0, accuracy=0.0)


@dataclass(frozen=True, slots=True)
class Sufficiency:
    """Deliberately computed apart from risk. Conflating the two is the bug
    this whole system exists to fix.

    A term set to None means "not measured yet", which is not the same as
    measured-and-fine. Such terms are dropped and the remaining weights
    renormalised, so an unbuilt component can never contribute confidence it
    has not earned. Letting a placeholder read as evidence would reproduce,
    inside this engine, the exact failure it exists to detect.
    """

    entropy: float | None = None        # 1 - normalised posterior entropy
    coverage: float | None = None       # weighted reliability mass, actual/ideal
    contradiction: float | None = None  # 1 - contradiction mass
    staleness: float | None = None      # 1 - worst-case staleness
    ceiling: float = 1.0                # cap imposed by a missing critical source

    @property
    def measured_terms(self) -> dict[str, float]:
        candidates = {
            "entropy": self.entropy,
            "coverage": self.coverage,
            "contradiction": self.contradiction,
            "staleness": self.staleness,
        }
        return {name: value for name, value in candidates.items() if value is not None}

    @property
    def score(self) -> float:
        measured = self.measured_terms
        if not measured:
            return 0.0
        weights = config.SUFFICIENCY_WEIGHTS
        total_weight = sum(weights[name] for name in measured)
        if total_weight <= 0:
            return 0.0
        weighted = sum(weights[name] * value for name, value in measured.items())
        return min(weighted / total_weight, self.ceiling)


@dataclass(frozen=True, slots=True)
class RecommendedCheck:
    """A verification step, with what knowing would be worth."""

    key: str
    label: str
    value: float            # expected harm averted by knowing the answer
    value_per_cost: float
    cost: float
    latency_minutes: int
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ZoneAssessment:
    """What the engine concludes about one zone at one tick."""

    geoid: str
    risk: float
    sufficiency: Sufficiency
    state: DecisionState
    posterior: dict[str, float] = field(default_factory=dict)
    contributing: dict[str, float] = field(default_factory=dict)  # source -> reliability
    contradictions: tuple[str, ...] = ()
    recommended_checks: tuple[RecommendedCheck, ...] = ()
    current_decision: str = ""
    unseen_danger: float = 0.0
    unresolved_harm: float = 0.0   # ranking key for operator attention
