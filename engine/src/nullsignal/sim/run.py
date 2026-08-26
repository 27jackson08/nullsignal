"""Scenario execution.

Each tick: advance ground truth, synthesise the observations a faithful
instrument would produce, corrupt them with whatever faults are active, then
let both engines judge the corrupted picture. Ground truth is recorded but
never shown to either engine, which is what makes the result a measurement
rather than a demonstration.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..eval import baseline
from ..inference import engine
from ..inference.evidence import ZoneEvidence
from ..inference.hypotheses import World
from ..types import DecisionState
from ..reliability.climate_check import apply_to_cohort as apply_climate
from ..reliability.consistency import apply_to_cohort
from . import injectors
from .scenario import Scenario, WorldState, is_harmful, true_world

# Reports a tract files when something is actually wrong, relative to its own
# usual rate. Distress is visible in the data before anyone models it.
DISTRESS_TEMPO = 2.1
CALM_TEMPO = 1.0

# Service alerts a genuine disruption produces.
DISRUPTION_ALERTS = 3


@dataclass(frozen=True, slots=True)
class TickRecord:
    tick: int
    hour: float
    geoid: str
    population: int
    svi: float | None
    truth: World
    truth_harmful: bool
    nullsignal_state: DecisionState
    baseline_state: DecisionState
    nullsignal_risk: float
    nullsignal_sufficiency: float
    unresolved_harm: float
    active_faults: tuple[str, ...]

    @property
    def nullsignal_falsely_reassured(self) -> bool:
        return self.truth_harmful and self.nullsignal_state.is_reassuring

    @property
    def baseline_falsely_reassured(self) -> bool:
        return self.truth_harmful and self.baseline_state.is_reassuring


@dataclass(frozen=True, slots=True)
class RunResult:
    scenario: Scenario
    records: tuple[TickRecord, ...]
    injected_at: dict[str, float]


def run(
    scenario: Scenario,
    base_evidence: list[ZoneEvidence],
    climate_normal: dict | None = None,
) -> RunResult:
    state = WorldState()
    pending = list(scenario.events)
    records: list[TickRecord] = []

    last_good: dict[str, ZoneEvidence] = {}
    fault_ticks: dict[str, int] = {}
    thresholds: baseline.BaselineThresholds | None = None

    for tick in range(scenario.tick_count):
        hour = scenario.hour_of(tick)
        while pending and pending[0].at_hour <= hour:
            state.apply(pending.pop(0), hour)

        for key in state.active:
            fault_ticks[key] = fault_ticks.get(key, 0) + 1

        # Both engines see the same corrupted cohort, so neither gets an
        # advantage from a cleaner view of the world.
        observed = []
        for item in base_evidence:
            truth = true_world(state, item.zone)
            faithful = _faithful_view(item, state, truth)
            corrupted = injectors.apply(
                faithful, state.injections,
                last_good=last_good.get(item.zone.geoid),
                ticks_active=fault_ticks,
            )
            last_good[item.zone.geoid] = faithful
            observed.append((truth, corrupted))

        # Cross-station agreement is a relation across the cohort, so it is
        # applied here rather than inside the per-zone assessment.
        checked = apply_climate(
            apply_to_cohort([e for _, e in observed]), climate_normal)
        observed = list(zip((t for t, _ in observed), checked))

        # Calibrated once, on the opening distribution, and held for the rest
        # of the run. Re-deriving the percentile every tick would give the
        # baseline a property no deployed dashboard has: its alert count would
        # stay pinned at the top decile no matter how bad the city got, so it
        # could neither escalate into a worsening heatwave nor notice reporting
        # collapsing underneath it. Real thresholds are tuned on normal
        # conditions and then left alone.
        if thresholds is None:
            thresholds = baseline.calibrate([e for _, e in observed])

        faults = tuple(sorted(state.active))

        for truth, corrupted in observed:
            ours = engine.assess(corrupted, rank_checks=False)
            theirs = baseline.assess(corrupted, thresholds)
            records.append(TickRecord(
                tick=tick,
                hour=hour,
                geoid=corrupted.zone.geoid,
                population=corrupted.zone.population,
                svi=corrupted.zone.svi_overall,
                truth=truth,
                truth_harmful=is_harmful(truth),
                nullsignal_state=ours.state,
                baseline_state=theirs.state,
                nullsignal_risk=ours.risk,
                nullsignal_sufficiency=ours.sufficiency.score,
                unresolved_harm=ours.unresolved_harm,
                active_faults=faults,
            ))

    return RunResult(scenario, tuple(records), dict(state.injected_at))


def _faithful_view(
    item: ZoneEvidence,
    state: WorldState,
    truth: World,
) -> ZoneEvidence:
    """What honest instruments would report, given the truth.

    Derived from ground truth rather than sampled, so a run is exactly
    reproducible -- the scoreboard has to be re-checkable, or it is an anecdote.
    """
    tempo = DISTRESS_TEMPO if is_harmful(truth) else CALM_TEMPO
    baseline_recent = max(
        1, round(item.report_count * 48.0 / max(item.report_window_hours, 1.0))
    )
    return replace(
        item,
        heat_index_f=state.heat_index_f,
        transit_alerts=DISRUPTION_ALERTS if state.transit_disrupted else 0,
        recent_report_count=round(baseline_recent * tempo),
    )
