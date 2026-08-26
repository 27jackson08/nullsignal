"""Contradiction detection across sources.

The rule that matters here is what we do *not* do: contradictions are never
fused. Averaging "transit halted" with "transit normal" into "mildly degraded"
would launder a crisis into a shrug, and produce a confident-looking number
with nothing behind it. A conflict widens uncertainty instead -- it lowers
sufficiency and leaves the risk estimate exactly where it was.

Two limits on how far that goes, both measured rather than assumed:

Conflict carries 20% of the sufficiency weight, and the decision threshold sits
at 0.55, so a fully saturated contradiction on its own lands at 0.80 and cannot
by itself move a zone to UNKNOWN. It contributes; it does not decide. See
`test_contradiction_alone_cannot_withhold_a_verdict`.

And a direct conflict requires two sources making claims about the *same*
proposition. This system has one source per subject -- one transit feed, one
weather provider -- so in practice only the inferential rules below ever fire.
That is the root cause of both scenarios NullSignal loses: a sole witness
lying well leaves nothing to disagree with it.
"""
from __future__ import annotations

from dataclasses import dataclass

from .types import Claim, Contradiction, Subject

# Heat bands at which residents of a normally-vocal tract would be expected to
# call 311 about something.
DANGEROUS_HEAT = frozenset({"high", "extreme"})

# Heat bands at which no instrument is claiming anything is wrong, so an
# elevated volume of complaints has nothing to explain it.
BENIGN_HEAT = frozenset({"low", "moderate"})

# Contradiction mass at which sufficiency is fully forfeit.
SATURATION_MASS = 1.0


@dataclass(frozen=True, slots=True)
class ContradictionGraph:
    claims: tuple[Claim, ...]
    contradictions: tuple[Contradiction, ...]

    @property
    def mass(self) -> float:
        """Total weight of conflict, capped.

        Summed rather than maxed, unlike the liveness detectors: two different
        pairs of sources disagreeing about two different things really is worse
        than one, because each conflict is its own independent unresolved
        question.
        """
        return min(SATURATION_MASS, sum(c.weight for c in self.contradictions))

    @property
    def agreement(self) -> float:
        """The sufficiency term: 1 when nothing conflicts, 0 when saturated."""
        return 1.0 - self.mass

    def describe(self) -> tuple[str, ...]:
        return tuple(c.describe() for c in self.contradictions)


def build(claims: tuple[Claim, ...]) -> ContradictionGraph:
    by_subject: dict[Subject, list[Claim]] = {}
    for claim in claims:
        by_subject.setdefault(claim.subject, []).append(claim)

    found: list[Contradiction] = []
    found.extend(_direct_conflicts(by_subject))
    found.extend(_expected_but_absent(by_subject))
    found.extend(_unexplained_distress(by_subject))
    return ContradictionGraph(claims, tuple(found))


def _direct_conflicts(by_subject: dict[Subject, list[Claim]]) -> list[Contradiction]:
    """Two sources asserting different values for the same proposition."""
    conflicts: list[Contradiction] = []
    for subject, group in by_subject.items():
        for i, left in enumerate(group):
            for right in group[i + 1:]:
                if left.value != right.value:
                    conflicts.append(Contradiction(
                        left, right,
                        reason=f"two sources disagree about {subject}",
                    ))
    return conflicts


def _expected_but_absent(by_subject: dict[Subject, list[Claim]]) -> list[Contradiction]:
    """Silence where this tract would normally be speaking.

    Dangerous heat with falling complaint volume is only surprising in a tract
    whose silence is worth reading -- which is what the propensity model
    measures, and why the distress claim carries the tract's evidential weight
    as its reliability rather than the feed's uptime. In a tract that rarely
    calls 311 at all, quiet is the normal condition and no conflict is raised.
    """
    heat_claims = by_subject.get(Subject.HEAT_EXPOSURE, [])
    distress_claims = by_subject.get(Subject.POPULATION_DISTRESS, [])

    conflicts: list[Contradiction] = []
    for heat in heat_claims:
        if heat.value not in DANGEROUS_HEAT:
            continue
        for distress in distress_claims:
            if distress.value != "low":
                continue
            conflicts.append(Contradiction(
                heat, distress,
                reason=("dangerous heat, yet this tract has gone quieter than "
                        "its own usual rate"),
            ))
    return conflicts


def _unexplained_distress(by_subject: dict[Subject, list[Claim]]) -> list[Contradiction]:
    """Residents calling well above their own rate while every instrument says
    nothing is happening.

    The mirror of `_expected_but_absent`, and the only trace a slow citywide
    sensor drift leaves. A thermometer biased toward the seasonal normal cannot
    be caught by cross-station agreement -- every station moves together -- nor
    by the climatology band, because the normal is exactly where the reading
    lands. What it cannot do is stop people who are actually hot from calling
    311.

    Two things make this safe to raise. It requires a hazard claim that says
    benign, not merely the absence of one: a source we do not trust has not
    told us the weather is fine, and treating its silence as "fine" is the bug
    this project exists to prevent. And it is a contradiction rather than
    evidence of danger, so it lowers sufficiency and leaves the risk estimate
    untouched -- an unexplained surge in complaints is a reason to stop
    certifying safety, not a reason to claim an emergency. People call 311
    about a great many things that are not heat.
    """
    heat_claims = by_subject.get(Subject.HEAT_EXPOSURE, [])
    distress_claims = by_subject.get(Subject.POPULATION_DISTRESS, [])
    if not heat_claims:
        return []

    conflicts: list[Contradiction] = []
    for distress in distress_claims:
        if distress.value != "elevated":
            continue
        for heat in heat_claims:
            if heat.value not in BENIGN_HEAT:
                continue
            conflicts.append(Contradiction(
                heat, distress,
                reason=("residents are reporting well above their own usual "
                        "rate, and no instrument accounts for it"),
            ))
    return conflicts
