"""Scoreboard: what a run actually showed.

Both engines see the same corrupted evidence and neither sees ground truth, so
every number here is a measurement rather than a demonstration.

The headline is **false reassurance** -- how often an engine called a place
safe while people were in danger. It is reported population-weighted as well as
per zone-hour, because 200 residents wrongly reassured and 20,000 wrongly
reassured are not the same failure.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..sim.run import RunResult, TickRecord
from ..types import DecisionState

# Vulnerability quintile used for the concentration metric.
TOP_QUINTILE = 0.8

# Share of the endangered cohort an engine must stop calling safe before it
# counts as having reacted. Without a quorum, a handful of tracts that were
# already flagged for unrelated reasons make an engine look prescient from
# hour zero -- which is how both engines first scored an identical, and
# identically meaningless, nine hours of warning.
REACTION_QUORUM = 0.5


@dataclass(frozen=True, slots=True)
class EngineScore:
    name: str
    false_reassurance_rate: float
    residents_falsely_reassured: int
    false_alarm_rate: float
    unresolved_rate: float
    harmful_zone_hours: int
    calm_zone_hours: int
    detection_lead_hours: float | None
    warning_hours: float | None

    @property
    def alarms_indiscriminately(self) -> bool:
        """True when a low false-reassurance rate was bought by alarming.

        Any engine can score zero false reassurance by never calling anything
        safe. Reporting the two rates side by side is what stops that from
        looking like skill.
        """
        return self.false_alarm_rate > 0.4

    def as_row(self) -> dict:
        return {
            "engine": self.name,
            "false_reassurance_rate": round(self.false_reassurance_rate, 4),
            "residents_falsely_reassured": self.residents_falsely_reassured,
            "false_alarm_rate": round(self.false_alarm_rate, 4),
            "unresolved_rate": round(self.unresolved_rate, 4),
            "detection_lead_hours": self.detection_lead_hours,
            "warning_hours": self.warning_hours,
        }


@dataclass(frozen=True, slots=True)
class Scoreboard:
    scenario: str
    nullsignal: EngineScore
    baseline: EngineScore
    blind_spot_concentration: float
    citywide_top_quintile_share: float
    concentration_ratio: float
    residents_at_risk: int

    @property
    def lead_time_advantage(self) -> float | None:
        if self.nullsignal.detection_lead_hours is None:
            return None
        if self.baseline.detection_lead_hours is None:
            return float("inf")
        return self.baseline.detection_lead_hours - self.nullsignal.detection_lead_hours


def score(result: RunResult) -> Scoreboard:
    records = result.records
    harmful = [r for r in records if r.truth_harmful]
    calm = [r for r in records if not r.truth_harmful]

    # Measured from when the concealed harm *began*, not from when the fault
    # was injected. A fault that precedes the danger it will later hide would
    # otherwise yield a negative lead time for an engine that reacted the
    # instant there was anything to react to.
    onset_hour = min((r.hour for r in harmful), default=None)

    ours = _score_engine(
        "nullsignal", records, harmful, calm,
        reassured=lambda r: r.nullsignal_falsely_reassured,
        alarmed=lambda r: not r.nullsignal_state.is_reassuring,
        claiming_danger=lambda r: _claims_danger(r.nullsignal_state),
        unresolved=lambda r: r.nullsignal_state is DecisionState.UNKNOWN,
        onset_hour=onset_hour,
    )
    theirs = _score_engine(
        "baseline", records, harmful, calm,
        reassured=lambda r: r.baseline_falsely_reassured,
        alarmed=lambda r: not r.baseline_state.is_reassuring,
        claiming_danger=lambda r: _claims_danger(r.baseline_state),
        unresolved=lambda r: r.baseline_state is DecisionState.UNKNOWN,
        onset_hour=onset_hour,
    )

    concentration, citywide = _blind_spot_concentration(records)
    return Scoreboard(
        scenario=result.scenario.name,
        nullsignal=ours,
        baseline=theirs,
        blind_spot_concentration=concentration,
        citywide_top_quintile_share=citywide,
        concentration_ratio=(concentration / citywide) if citywide > 0 else 0.0,
        residents_at_risk=_residents(harmful),
    )


def _claims_danger(state: DecisionState) -> bool:
    """States that assert something is wrong, as opposed to declining to say."""
    return state in (DecisionState.CONFIRMED_HIGH, DecisionState.SUSPECTED)


def _score_engine(
    name: str,
    records: tuple[TickRecord, ...],
    harmful: list[TickRecord],
    calm: list[TickRecord],
    *,
    reassured,
    alarmed,
    claiming_danger,
    unresolved,
    onset_hour: float | None,
) -> EngineScore:
    wrongly_calm = [r for r in harmful if reassured(r)]

    # A false alarm is *claiming danger* while nothing is wrong. Tracked so a
    # low false-reassurance rate cannot be bought by flagging everything.
    #
    # UNKNOWN is counted separately and deliberately. Saying "we cannot confirm
    # this is safe" is not crying wolf -- it asserts nothing about danger, and
    # it is the behaviour this system exists to produce. Folding it into the
    # false-alarm rate made honesty look like noise: the canonical scenario
    # read 33% "false alarms" that were almost entirely a frozen transit feed
    # after the heat eased, where declining to certify was exactly right.
    #
    # Both are reported. Neither is hidden inside the other.
    false_alarms = [r for r in calm if claiming_danger(r)]
    unresolved_while_calm = [r for r in calm if unresolved(r)]

    return EngineScore(
        name=name,
        false_reassurance_rate=len(wrongly_calm) / len(harmful) if harmful else 0.0,
        residents_falsely_reassured=_residents(wrongly_calm),
        false_alarm_rate=len(false_alarms) / len(calm) if calm else 0.0,
        unresolved_rate=len(unresolved_while_calm) / len(calm) if calm else 0.0,
        harmful_zone_hours=len(harmful),
        calm_zone_hours=len(calm),
        detection_lead_hours=_detection_hour(harmful, alarmed, onset_hour),
        warning_hours=_warning_hours(records, harmful, alarmed, onset_hour),
    )


def _detection_hour(
    harmful: list[TickRecord],
    alarmed,
    onset_hour: float | None,
) -> float | None:
    """Hours from the onset of real danger to the first time this engine
    stopped calling an endangered tract safe.

    None means it never stopped -- which is the interesting result, not a
    missing measurement.
    """
    if onset_hour is None:
        return None
    flagged = [r.hour for r in harmful if alarmed(r)]
    if not flagged:
        return None
    return round(min(flagged) - onset_hour, 2)


def _warning_hours(
    records: tuple[TickRecord, ...],
    harmful: list[TickRecord],
    alarmed,
    onset_hour: float | None,
) -> float | None:
    """How long before the danger began this engine stopped calling those
    tracts safe.

    The metric that separates the two engines here, where raw detection time
    does not. Both react the moment harm arrives; only one reacts *before* it,
    because only one can see that its instruments went dark two hours earlier.
    A negative value means the engine was still reassuring when harm began.
    """
    if onset_hour is None:
        return None
    endangered = {r.geoid for r in harmful}
    if not endangered:
        return None

    by_hour: dict[float, list[TickRecord]] = {}
    for record in records:
        if record.geoid in endangered and record.hour <= onset_hour:
            by_hour.setdefault(record.hour, []).append(record)

    reacted = [
        hour for hour, cohort in sorted(by_hour.items())
        if cohort and sum(1 for r in cohort if alarmed(r)) / len(cohort) >= REACTION_QUORUM
    ]
    if not reacted:
        return 0.0
    return round(onset_hour - min(reacted), 2)


def _blind_spot_concentration(records: tuple[TickRecord, ...]) -> tuple[float, float]:
    """Who lives in the places a conventional dashboard keeps calling safe.

    Replaces the false-reassurance-by-propensity split originally planned. In
    NYC, reporting propensity does not fall with vulnerability -- so that metric
    would have reported a gap the data does not support. What the data does
    support is concentration: where the system goes blind, who is standing
    there.
    """
    blind = [r for r in records if r.baseline_falsely_reassured and r.svi is not None]
    everyone = [r for r in records if r.svi is not None]

    return (
        _top_quintile_share(blind),
        _top_quintile_share(everyone),
    )


def _top_quintile_share(records: list[TickRecord]) -> float:
    """Population share in the top vulnerability quintile.

    Both sides deduplicate by tract. Summing the numerator over zone-*hours*
    while the denominator counted tracts once produced shares above 100%.
    """
    by_zone = {r.geoid: r for r in records}
    total = sum(r.population for r in by_zone.values())
    if total <= 0:
        return 0.0
    top = sum(r.population for r in by_zone.values() if (r.svi or 0) >= TOP_QUINTILE)
    return top / total


def _residents(records) -> int:
    """Population summed over distinct zones, not zone-hours: a tract wrongly
    reassured for six hours is still one tract's worth of people."""
    return sum({r.geoid: r.population for r in records}.values())
