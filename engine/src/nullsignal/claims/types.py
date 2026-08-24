"""Typed claims extracted from evidence.

Sources do not disagree about raw numbers; they disagree about what is
happening. Lifting each source's reading into an explicit proposition is what
makes disagreement detectable at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Subject(StrEnum):
    """What a claim is about."""

    TRANSIT_SERVICE = "transit_service"
    HEAT_EXPOSURE = "heat_exposure"
    POPULATION_DISTRESS = "population_distress"


@dataclass(frozen=True, slots=True)
class Claim:
    subject: Subject
    value: str
    source: str
    reliability: float   # how much this source's word is worth here, 0..1
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.source} says {self.subject}={self.value}"


@dataclass(frozen=True, slots=True)
class Contradiction:
    """Two claims that cannot both be true, weighted by the weaker source.

    `min` rather than a product or an average: a conflict is only as compelling
    as the *weaker* of the two sources making it. Two unreliable sources
    disagreeing is noise; two reliable ones disagreeing is a real problem.
    """

    left: Claim
    right: Claim
    reason: str

    @property
    def weight(self) -> float:
        return min(self.left.reliability, self.right.reliability)

    def describe(self) -> str:
        return f"{self.left} but {self.right} — {self.reason}"
