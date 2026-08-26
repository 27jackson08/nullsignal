"""The shift briefing.

Everything else in this project is an argument. This is the part someone uses.

A duty officer during a heat emergency has a small number of crews and a whole
city. The question is not "what is the risk map" -- it is "where do I send
people, and what should they do when they get there". A conventional dashboard
cannot answer it, because the places worth visiting are precisely the ones it
has nothing to say about.

So the briefing ranks by *unresolved harm times the people it falls on*, states
what is blocking the call, and names one action with a time on it. It is meant
to be printed and carried.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..inference.evidence import ZoneEvidence
from ..labels import source as source_label
from ..types import DecisionState, ZoneAssessment

# A briefing longer than this stops being a shift's work and becomes a report.
ASSIGNMENT_LIMIT = 8


@dataclass(frozen=True, slots=True)
class Briefing:
    issued_at: str | None
    uncertifiable_tracts: int
    uncertifiable_residents: int
    top_quintile_share: float
    citywide_top_quintile_share: float
    assignments: tuple[dict, ...]
    check_tally: tuple[dict, ...]

    @property
    def residents_on_the_list(self) -> int:
        return sum(a["population"] for a in self.assignments)

    @property
    def concentration(self) -> float:
        if self.citywide_top_quintile_share <= 0:
            return 0.0
        return self.top_quintile_share / self.citywide_top_quintile_share

    def as_dict(self) -> dict:
        return {
            "issued_at": self.issued_at,
            "situation": {
                "uncertifiable_tracts": self.uncertifiable_tracts,
                "uncertifiable_residents": self.uncertifiable_residents,
                "top_quintile_share": self.top_quintile_share,
                "citywide_top_quintile_share": self.citywide_top_quintile_share,
                "concentration": self.concentration,
            },
            "assignments": list(self.assignments),
            "check_tally": list(self.check_tally),
            "residents_on_the_list": self.residents_on_the_list,
        }


def build(
    assessed: list[tuple[ZoneEvidence, ZoneAssessment]],
    *,
    issued_at: str | None = None,
    top_quintile: float | None = None,
    limit: int = ASSIGNMENT_LIMIT,
) -> Briefing:
    unresolved = [
        (item, ours) for item, ours in assessed
        if ours.state is DecisionState.UNKNOWN and item.zone.population > 0
    ]

    ranked = sorted(
        unresolved,
        key=lambda pair: pair[1].unresolved_harm * pair[0].zone.population,
        reverse=True,
    )

    assignments = tuple(
        _assignment(rank, item, ours)
        for rank, (item, ours) in enumerate(ranked[:limit], start=1)
    )

    # Which check the city needs most of tonight, across every unresolved
    # tract rather than only the ones that fit on the page.
    tally: dict[str, dict] = {}
    for item, ours in unresolved:
        check = ours.recommended_checks[0] if ours.recommended_checks else None
        if check is None:
            continue
        row = tally.setdefault(
            check.label, {"check": check.label, "tracts": 0, "residents": 0,
                          "minutes": check.latency_minutes},
        )
        row["tracts"] += 1
        row["residents"] += item.zone.population

    return Briefing(
        issued_at=issued_at,
        uncertifiable_tracts=len(unresolved),
        uncertifiable_residents=sum(i.zone.population for i, _ in unresolved),
        top_quintile_share=_share(unresolved, top_quintile),
        citywide_top_quintile_share=_share(assessed, top_quintile),
        assignments=assignments,
        check_tally=tuple(sorted(tally.values(),
                                 key=lambda r: r["residents"], reverse=True)),
    )


def _assignment(rank: int, item: ZoneEvidence, ours: ZoneAssessment) -> dict:
    check = ours.recommended_checks[0] if ours.recommended_checks else None
    return {
        "rank": rank,
        "geoid": item.zone.geoid,
        "name": item.zone.name,
        "borough": item.zone.borough,
        "population": item.zone.population,
        "residents_at_stake": round(ours.unresolved_harm * item.zone.population),
        "blind_because": _blockers(item, ours),
        "check": None if check is None else {
            "label": check.label,
            "minutes": check.latency_minutes,
            "detail": check.detail,
        },
    }


def _blockers(item: ZoneEvidence, ours: ZoneAssessment) -> tuple[str, ...]:
    """Why this tract cannot be called, in the order that matters.

    A missing source outranks a conflict: if the evidence is not there at all,
    resolving a disagreement between the sources that remain does not get us to
    a verdict.
    """
    reasons = [
        f"{source_label(name)} is unavailable here"
        for name in item.missing_critical_sources
    ]
    reasons.extend(ours.contradictions)
    if not reasons:
        reasons.append(
            "the evidence is present but too thin to support a call either way"
        )
    return tuple(reasons)


def _share(pairs, quintile: float | None) -> float:
    """Share of residents in the most vulnerable fifth of the city."""
    if quintile is None:
        return 0.0
    total = top = 0
    for item, _ in pairs:
        population = item.zone.population
        total += population
        svi = item.zone.svi_overall
        if svi is not None and svi >= quintile:
            top += population
    return 0.0 if not total else top / total
