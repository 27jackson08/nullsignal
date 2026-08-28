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
from ..voi import resolution

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
    def minutes_to_clear_the_city(self) -> int:
        """Crew-minutes to settle every blind spot a crew could settle.

        Worth stating because it is small: the objection to treating doubt as
        actionable is that acting on it does not scale, and the tally says what
        it would actually cost. Worth bounding for the same reason -- it covers
        the tracts a check can reach, and `unreachable_tracts` is the rest.
        """
        return sum(row["tracts"] * row["minutes"] for row in self.check_tally)

    @property
    def reachable_tracts(self) -> int:
        return sum(row["tracts"] for row in self.check_tally)

    @property
    def unreachable_tracts(self) -> int:
        """Blind spots no field action can settle, at any cost."""
        return self.uncertifiable_tracts - self.reachable_tracts

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
            "minutes_to_clear_the_city": self.minutes_to_clear_the_city,
            "reachable_tracts": self.reachable_tracts,
            "unreachable_tracts": self.unreachable_tracts,
        }


def build(
    assessed: list[tuple[ZoneEvidence, ZoneAssessment]],
    *,
    issued_at: str | None = None,
    top_quintile: float | None = None,
    limit: int = ASSIGNMENT_LIMIT,
    assess=None,
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

    if assess is None:
        from ..inference.engine import assess as assess

    assignments = tuple(
        _assignment(rank, item, ours, assess)
        for rank, (item, ours) in enumerate(ranked[:limit], start=1)
    )

    # Which check the city needs most of tonight, across every unresolved
    # tract rather than only the ones that fit on the page. Counted on the
    # check that would resolve the tract, not the one with the highest
    # decision value -- a tally of errands that cannot answer the question
    # would misdescribe the night's work.
    tally: dict[str, dict] = {}
    for item, _ in unresolved:
        found = resolution.cheapest_resolving(item, assess=assess)
        if found is None:
            continue
        row = tally.setdefault(
            found.action.label,
            {"check": found.action.label, "tracts": 0, "residents": 0,
             "minutes": found.action.latency_minutes},
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


def _assignment(
    rank: int, item: ZoneEvidence, ours: ZoneAssessment, assess
) -> dict:
    """One line of the work order.

    The check named is the one that would let the tract be called, which is not
    the one with the highest value of information. VOI scores how much a result
    would change the *response*; for a tract nobody can call, the operator's
    question is what would let them call it. Both are reported, because they
    answer different questions and conflating them is the error this project
    exists to name.
    """
    resolving = resolution.cheapest_resolving(item, assess=assess)
    highest_value = ours.recommended_checks[0] if ours.recommended_checks else None

    also = None
    if highest_value is not None and (
        resolving is None or highest_value.key != resolving.action.key
    ):
        also = {
            "label": highest_value.label,
            "minutes": highest_value.latency_minutes,
            "detail": highest_value.detail,
        }

    return {
        "rank": rank,
        "geoid": item.zone.geoid,
        "name": item.zone.name,
        "borough": item.zone.borough,
        "population": item.zone.population,
        "residents_at_stake": round(ours.unresolved_harm * item.zone.population),
        "state": ours.state.value,
        "sufficiency": round(ours.sufficiency.score, 4),
        "blind_because": _blockers(item, ours),
        "nothing_resolves": None if resolving is not None else _why_stuck(item),
        "check": None if resolving is None else {
            "key": resolving.action.key,
            "label": resolving.action.label,
            "minutes": resolving.action.latency_minutes,
            "detail": resolving.action.detail,
            # What the tract becomes if it comes back clear. Precomputed so the
            # loop can close without a backend, and it is the engine's own
            # answer rather than an animation.
            "resolves_to": {
                "state": resolving.state,
                "sufficiency": resolving.sufficiency,
                "risk": resolving.risk,
            },
        },
        "also_worth_doing": also,
    }


def _why_stuck(item: ZoneEvidence) -> str:
    """Why no crew can settle this one.

    Worth stating rather than leaving as a blank action. A tract whose
    vulnerability index CDC has suppressed cannot be resolved by looking at it:
    an inspector sees the weather, the service and the street, and no amount of
    looking produces a census statistic. That is a publication problem wearing
    the appearance of an operational one, and sending a crew would waste a
    shift on it.
    """
    missing = set(item.missing_critical_sources)
    if "cdc_svi" in missing:
        return ("the vulnerability data for this tract is suppressed at source, "
                "and no field check can produce it")
    if missing:
        named = ", ".join(source_label(name) for name in sorted(missing))
        return f"nothing in the catalogue substitutes for {named}"
    return "the evidence is thin in a way no single check would settle"


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
