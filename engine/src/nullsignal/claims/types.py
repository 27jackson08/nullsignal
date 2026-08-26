"""Typed claims extracted from evidence.

Sources do not disagree about raw numbers; they disagree about what is
happening. Lifting each source's reading into an explicit proposition is what
makes disagreement detectable at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..labels import source as source_label


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

    def phrase(self) -> str:
        """The same claim in a sentence an operator can read.

        `__str__` stays machine-shaped for logs and test assertions; this is
        what reaches the tract panel and the written explanation.
        """
        readable = _PHRASINGS.get((self.subject, self.value))
        if readable is not None:
            return readable
        return f"{source_label(self.source)} reports {self.subject} is {self.value}"


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
        return f"{_sentence(self.left.phrase())}, but {self.right.phrase()} — {self.reason}."


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


# One phrasing per proposition. Written out rather than composed from parts
# because "the weather service reports heat_exposure is high" is not a sentence
# anyone would say, and this text is read by people deciding where to send a
# crew.
_PHRASINGS: dict[tuple[Subject, str], str] = {
    (Subject.TRANSIT_SERVICE, "normal"):
        "the transit feed reports service running normally",
    (Subject.TRANSIT_SERVICE, "degraded"):
        "the transit feed reports degraded service",

    (Subject.HEAT_EXPOSURE, "low"):
        "the weather service reports mild conditions",
    (Subject.HEAT_EXPOSURE, "moderate"):
        "the weather service reports moderate heat",
    (Subject.HEAT_EXPOSURE, "high"):
        "the weather service reports dangerous heat",
    (Subject.HEAT_EXPOSURE, "extreme"):
        "the weather service reports extreme heat",

    (Subject.POPULATION_DISTRESS, "low"):
        "residents are calling 311 less than this tract normally does",
    (Subject.POPULATION_DISTRESS, "normal"):
        "residents are calling 311 at about this tract's usual rate",
    (Subject.POPULATION_DISTRESS, "elevated"):
        "residents are calling 311 well above this tract's usual rate",
}
