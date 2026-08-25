"""The evidence packet: everything the language model is allowed to see.

What is *absent* here is the design. The packet carries no risk score, no
decision state, and no recommendation about whether anyone is safe. Those are
produced by the deterministic and probabilistic layers, and the model's job is
to say what the evidence is -- not to decide what it means.

Handing a model the verdict and asking it to justify the verdict produces
fluent advocacy for whatever it was handed, including when the verdict is
wrong. A system whose entire claim is epistemic honesty cannot have a component
that argues for conclusions it did not reach.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..inference.evidence import ZoneEvidence
from ..types import ZoneAssessment

SOURCE_LABELS = {
    "nws": "the weather service",
    "cdc_svi": "the vulnerability index",
    "gtfs_rt": "the transit realtime feed",
    "311": "resident reports",
}


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    """Verifiable facts about one zone, and nothing else."""

    zone_name: str
    borough: str
    population: int
    facts: dict[str, float] = field(default_factory=dict)
    observations: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    next_check: str = ""
    next_check_minutes: int | None = None

    @property
    def fingerprint(self) -> str:
        """Stable hash of the packet, used to cache explanations.

        Identical evidence must yield the identical sentence, so a demo replays
        for free and an operator seeing the same situation twice is not shown
        two differently-worded accounts of it.
        """
        payload = json.dumps({
            "zone": self.zone_name,
            "facts": {k: round(v, 4) for k, v in sorted(self.facts.items())},
            "observations": sorted(self.observations),
            "gaps": sorted(self.gaps),
            "conflicts": sorted(self.conflicts),
            "next_check": self.next_check,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def as_prompt_json(self) -> str:
        return json.dumps({
            "neighbourhood": self.zone_name,
            "borough": self.borough,
            "residents": self.population,
            "measurements": {k: round(v, 3) for k, v in sorted(self.facts.items())},
            "what_each_source_reports": list(self.observations),
            "evidence_we_do_not_have": list(self.gaps),
            "sources_that_disagree": list(self.conflicts),
            "highest_value_next_check": self.next_check,
        }, indent=2)


def build(evidence: ZoneEvidence, assessment: ZoneAssessment) -> EvidencePacket:
    """Assemble the packet from evidence and assessment.

    The assessment is read for *components* -- which sources were missing, what
    conflicts, what to check next -- never for its verdict.
    """
    facts: dict[str, float] = {"residents": float(evidence.zone.population)}
    observations: list[str] = []

    if evidence.heat_index_f is not None:
        facts["heat_index_f"] = round(evidence.heat_index_f, 1)
        observations.append(
            f"the weather service reports a heat index of "
            f"{facts['heat_index_f']:.0f}F"
        )

    facts["reports_60d"] = float(evidence.report_count)
    facts["reports_recent"] = float(evidence.recent_report_count)
    tempo = evidence.reporting_tempo
    if tempo is not None:
        facts["reporting_tempo"] = round(tempo, 2)
        direction = "below" if tempo < 1 else "above"
        observations.append(
            f"residents filed {evidence.recent_report_count} reports in the last "
            f"48 hours, {facts['reporting_tempo']:.2f} times this tract's own "
            f"usual rate and therefore {direction} it"
        )

    if evidence.propensity and evidence.propensity.is_estimated:
        facts["reporting_index"] = round(evidence.propensity.index, 2)
        observations.append(
            f"this tract reports at {facts['reporting_index']:.2f} times the rate "
            f"of a comparable one, so its silence carries "
            f"{evidence.propensity.evidential_weight:.2f} of the weight a typical "
            f"tract's would"
        )
        facts["silence_weight"] = round(evidence.propensity.evidential_weight, 2)

    for name, reliability in sorted(evidence.source_reliability.items()):
        label = SOURCE_LABELS.get(name, name)
        facts[f"reliability_{name}"] = round(reliability.score, 2)
        if reliability.liveness <= 0.5:
            observations.append(
                f"{label} is answering but its content has stopped changing"
            )

    gaps = [
        f"{SOURCE_LABELS.get(name, name)} is unavailable for this tract"
        for name in evidence.missing_critical_sources
    ]

    relief = evidence.zone.cooling_working
    if relief is not None:
        facts["heat_relief_reachable"] = round(relief, 2)
        unreachable = evidence.zone.unreachable_relief or 0.0
        if unreachable > 0.05:
            facts["heat_relief_listed_but_broken"] = round(unreachable, 2)
            # A gap rather than an observation: the city's own record asserts
            # relief here that is not working, so any plan that assumes people
            # can cool down nearby is resting on something untrue.
            gaps.append(
                "part of this tract's listed heat relief is broken or "
                "unactivated, so the record overstates what people can reach"
            )
        elif relief < 0.1:
            observations.append(
                "no working heat relief lies within walking distance"
            )

    check = assessment.recommended_checks[0] if assessment.recommended_checks else None
    return EvidencePacket(
        zone_name=evidence.zone.name,
        borough=evidence.zone.borough,
        population=evidence.zone.population,
        facts=facts,
        observations=tuple(observations),
        gaps=tuple(gaps),
        conflicts=assessment.contradictions,
        next_check=check.label if check else "",
        next_check_minutes=check.latency_minutes if check else None,
    )
