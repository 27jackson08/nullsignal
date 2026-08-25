"""Scenario execution, failure injection, and the scoreboard."""
from __future__ import annotations

import pytest

from nullsignal.eval import scoreboard
from nullsignal.inference.hypotheses import World
from nullsignal.sim import run as simrun
from nullsignal.sim.injectors import FailureMode, Injection, apply
from nullsignal.sim.scenario import Event, Scenario, WorldState, is_harmful, true_world
from nullsignal.types import Reliability

from helpers import make_evidence, make_propensity, make_zone


def synthetic_city(size: int = 40):
    """Half the tracts transit-dependent, spread across vulnerability.

    Report volumes are spread deliberately. With every tract on an identical
    count, the baseline's percentile calibration lands its threshold exactly on
    that count and it alarms on all of them -- a degenerate cohort that makes
    the comparison meaningless rather than a hard one.
    """
    cohort = []
    for i in range(size):
        dependent = i % 2 == 0
        cohort.append(make_evidence(
            zone=make_zone(
                geoid=f"3606100{i:04d}",
                pct_no_vehicle=0.85 if dependent else 0.10,
                svi_overall=min(0.99, 0.2 + i / size),
                population=4000,
            ),
            propensity=make_propensity(1.2),
            report_count=60 + i * 11,
            report_window_hours=1440.0,
            heat_index_f=84.0,
        ))
    return cohort


SILENT_FAILURE = Scenario(
    name="test-silent-failure",
    description="",
    duration_hours=12,
    tick_hours=1.0,
    events=(
        Event(at_hour=0, heat_index_f=84),
        Event(at_hour=5, heat_index_f=94),
        Event(at_hour=6, inject=Injection("gtfs_rt", FailureMode.STALE_BUT_200)),
        Event(at_hour=8, transit_disrupted=True),
    ),
)


# --- the day-5 invariant ------------------------------------------------------

def test_silent_failure_beats_baseline():
    """On the canonical scenario, NullSignal must not falsely reassure where a
    threshold dashboard does, and must react before the harm arrives.

    The whole project reduced to one assertion. The two engines see identical
    corrupted evidence and neither sees ground truth.
    """
    board = scoreboard.score(simrun.run(SILENT_FAILURE, synthetic_city()))

    assert board.baseline.false_reassurance_rate > 0.5
    assert board.nullsignal.false_reassurance_rate < 0.05
    assert board.nullsignal.warning_hours > 0, "must react before harm begins"
    assert board.baseline.warning_hours == 0


def test_neither_engine_is_shown_ground_truth():
    """Structural guard: the record carries truth for scoring only.

    If an engine ever read it the scoreboard would be meaningless, so the
    assessment inputs are checked to contain no world state.
    """
    from dataclasses import fields
    from nullsignal.inference.evidence import ZoneEvidence

    names = {f.name for f in fields(ZoneEvidence)}
    assert not names & {"truth", "world", "ground_truth"}


# --- ground truth -------------------------------------------------------------

def test_stranding_requires_someone_who_cannot_drive_away():
    """A transit outage strands the people who depend on transit.

    Applied citywide it would make the scoreboard meaningless, counting a
    commuter inconvenience as a mass-casualty event.
    """
    state = WorldState(heat_index_f=95.0, transit_disrupted=True)
    assert true_world(state, make_zone(pct_no_vehicle=0.9)) is World.HEAT_STRANDED
    assert true_world(state, make_zone(pct_no_vehicle=0.05)) is not World.HEAT_STRANDED


def test_heat_that_is_only_dangerous_if_you_cannot_leave():
    """94F is unremarkable for someone who can reach air conditioning and
    dangerous for someone who cannot. The interaction a temperature threshold
    cannot see."""
    mild_but_stranding = WorldState(heat_index_f=94.0, transit_disrupted=True)
    assert true_world(mild_but_stranding, make_zone(pct_no_vehicle=0.9)) is World.HEAT_STRANDED
    assert true_world(mild_but_stranding, make_zone(pct_no_vehicle=0.05)) is World.LOCAL_FAULT


def test_a_commuter_inconvenience_is_not_counted_as_harm():
    assert not is_harmful(World.LOCAL_FAULT)
    assert is_harmful(World.HEAT_STRANDED)
    assert is_harmful(World.HEAT)


# --- injectors ----------------------------------------------------------------

def test_stale_but_200_replays_the_last_good_value_and_kills_liveness():
    """The canonical silent failure: the value stays plausible, and the only
    trace is that the content stopped changing."""
    before = make_evidence(transit_alerts=0)
    now = make_evidence(transit_alerts=3)          # reality has changed
    corrupted = apply(now, (Injection("gtfs_rt", FailureMode.STALE_BUT_200),),
                      last_good=before, ticks_active={})

    assert corrupted.transit_alerts == 0, "must replay the pre-failure value"
    assert corrupted.source_reliability["gtfs_rt"].liveness == 0.0


def test_dropout_is_loud_where_freezing_is_quiet():
    dropped = apply(make_evidence(), (Injection("gtfs_rt", FailureMode.DROPOUT),),
                    last_good=None, ticks_active={})
    reliability = dropped.source_reliability["gtfs_rt"]
    assert reliability.coverage == 0.0 and reliability.freshness == 0.0


def test_suppress_lowers_recent_reports_without_touching_history():
    """The tract's own baseline is left alone, so its reporting tempo drops --
    which is exactly the signal the contradiction rule looks for."""
    original = make_evidence(report_count=300, recent_report_count=40)
    suppressed = apply(original, (Injection("311", FailureMode.SUPPRESS, factor=0.1),),
                       last_good=None, ticks_active={})
    assert suppressed.recent_report_count == 4
    assert suppressed.report_count == original.report_count


def test_slow_drift_reads_cooler_which_is_the_dangerous_direction():
    drifted = apply(make_evidence(heat_index_f=100.0),
                    (Injection("nws", FailureMode.SLOW_DRIFT, drift_f=5.0),),
                    last_good=None, ticks_active={"nws:SLOW_DRIFT": 2})
    assert drifted.heat_index_f < 100.0


def test_every_declared_failure_mode_is_implemented():
    evidence = make_evidence()
    for mode in FailureMode:
        result = apply(evidence, (Injection("gtfs_rt", mode),),
                       last_good=evidence, ticks_active={})
        assert result is not None, mode


# --- scoreboard arithmetic ----------------------------------------------------

def test_population_counts_tracts_not_tract_hours():
    """A tract wrongly reassured for six hours is still one tract of people.

    Regression: summing over zone-hours on one side of the concentration metric
    and over tracts on the other produced shares above 100%.
    """
    board = scoreboard.score(simrun.run(SILENT_FAILURE, synthetic_city()))
    assert 0.0 <= board.blind_spot_concentration <= 1.0
    assert 0.0 <= board.citywide_top_quintile_share <= 1.0


def test_an_engine_that_alarms_constantly_is_flagged_as_such():
    """Zero false reassurance is trivial to buy by never calling anything safe."""
    from nullsignal.eval.scoreboard import EngineScore
    stopped_clock = EngineScore("test", 0.0, 0, 0.85, 0.0, 10, 10, 0.0, 0.0)
    assert stopped_clock.alarms_indiscriminately


# --- scenario parsing ---------------------------------------------------------

def write_scenario(tmp_path, body: str):
    path = tmp_path / "s.yaml"
    path.write_text(body)
    return path


def test_a_scenario_round_trips(tmp_path):
    from nullsignal.sim import scenario as scenario_module

    path = write_scenario(tmp_path, """
name: round-trip
description: a test
duration_hours: 6
tick_hours: 1
timeline:
  - at_hour: 2
    heat_index_f: 95
    note: warming
  - at_hour: 0
    heat_index_f: 84
  - at_hour: 4
    inject: {source: gtfs_rt, mode: STALE_BUT_200}
""")
    loaded = scenario_module.load(path)
    assert loaded.name == "round-trip"
    assert loaded.tick_count == 7
    assert [e.at_hour for e in loaded.events] == [0, 2, 4], "events sort by hour"
    assert loaded.events[-1].inject.mode is FailureMode.STALE_BUT_200


def test_an_unknown_failure_mode_names_itself(tmp_path):
    from nullsignal.sim import scenario as scenario_module

    path = write_scenario(tmp_path, """
name: bad
timeline:
  - at_hour: 1
    inject: {source: gtfs_rt, mode: EXPLODES}
""")
    with pytest.raises(ValueError, match="failure mode"):
        scenario_module.load(path)


def test_an_event_without_an_hour_is_rejected(tmp_path):
    from nullsignal.sim import scenario as scenario_module

    path = write_scenario(tmp_path, "name: bad\ntimeline:\n  - heat_index_f: 90\n")
    with pytest.raises(ValueError, match="at_hour"):
        scenario_module.load(path)


def test_a_scenario_that_is_not_a_mapping_is_rejected(tmp_path):
    from nullsignal.sim import scenario as scenario_module

    with pytest.raises(ValueError, match="mapping"):
        scenario_module.load(write_scenario(tmp_path, "- just\n- a list\n"))


def test_the_shipped_scenarios_all_parse():
    """Guard on the fixtures themselves: a malformed scenario should fail in
    CI, not in front of an audience."""
    from pathlib import Path
    from nullsignal.sim import scenario as scenario_module

    directory = Path(__file__).resolve().parents[2] / "scenarios"
    paths = scenario_module.available(directory)
    assert len(paths) >= 4

    for path in paths:
        loaded = scenario_module.load(path)
        assert loaded.name and loaded.tick_count > 1, path.name
        assert loaded.description.strip(), f"{path.name} needs a description"


def test_declining_to_certify_is_not_counted_as_crying_wolf():
    """Two different failures, kept in two different columns.

    Saying "we cannot confirm this is safe" asserts nothing about danger. It is
    the behaviour this system exists to produce, and folding it into the
    false-alarm rate made honesty look like noise -- the canonical scenario
    read 33% "false alarms" that were almost entirely a still-frozen transit
    feed after the heat eased, where declining to certify was exactly right.
    """
    board = scoreboard.score(simrun.run(SILENT_FAILURE, synthetic_city()))

    assert board.nullsignal.false_alarm_rate == 0.0, "never claims danger falsely"
    assert board.nullsignal.unresolved_rate > 0, "does decline to certify"

    # The baseline has the opposite shape: it can cry wolf, and it structurally
    # cannot decline to certify anything.
    assert board.baseline.unresolved_rate == 0.0


def test_the_two_costs_are_reported_separately():
    from nullsignal.eval.scoreboard import EngineScore

    honest = EngineScore("honest", 0.0, 0, 0.0, 0.9, 10, 10, 0.0, 2.0)
    assert not honest.alarms_indiscriminately, \
        "declining to certify must not read as indiscriminate alarming"
