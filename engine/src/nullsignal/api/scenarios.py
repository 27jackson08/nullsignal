"""Scenario playback for the client.

A run is thirty-odd thousand zone-hour records. Sending them as objects would
be megabytes of repeated keys, so each tick ships as three strings of
single-character state codes positioned against a shared zone order. The whole
fourteen-hour run lands in roughly a hundred kilobytes, which is what makes
scrubbing through it feel immediate.
"""
from __future__ import annotations

from pathlib import Path

from ..eval.scoreboard import Scoreboard, score
from ..inference.evidence import ZoneEvidence
from ..sim import run as simrun
from ..sim import scenario as scenario_module
from ..types import DecisionState

# One character per state, so a tick is a string rather than an array.
STATE_CODE = {
    DecisionState.CONFIRMED_LOW: "L",
    DecisionState.CONFIRMED_HIGH: "H",
    DecisionState.SUSPECTED: "S",
    DecisionState.UNKNOWN: "U",
}
TRUTH_CODE = {
    "normal": "n",
    "heat": "h",
    "heat_stranded": "x",
    "local_fault": "f",
}


def list_scenarios(directory: Path) -> list[dict]:
    return [
        {
            "name": loaded.name,
            "description": " ".join(loaded.description.split()),
            "duration_hours": loaded.duration_hours,
            "event_count": len(loaded.events),
        }
        for loaded in (scenario_module.load(p) for p in scenario_module.available(directory))
    ]


def playback(
    directory: Path,
    name: str,
    evidence: list[ZoneEvidence],
    climate_normal: dict | None = None,
) -> dict:
    path = directory / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(name)

    loaded = scenario_module.load(path)
    result = simrun.run(loaded, evidence, climate_normal)

    zone_order = [item.zone.geoid for item in evidence]
    index = {geoid: position for position, geoid in enumerate(zone_order)}

    ticks: dict[int, dict] = {}
    for record in result.records:
        tick = ticks.setdefault(record.tick, {
            "hour": record.hour,
            "nullsignal": ["L"] * len(zone_order),
            "baseline": ["L"] * len(zone_order),
            "truth": ["n"] * len(zone_order),
            "faults": list(record.active_faults),
        })
        position = index[record.geoid]
        tick["nullsignal"][position] = STATE_CODE[record.nullsignal_state]
        tick["baseline"][position] = STATE_CODE[record.baseline_state]
        tick["truth"][position] = TRUTH_CODE.get(str(record.truth), "n")

    return {
        "name": loaded.name,
        "description": " ".join(loaded.description.split()),
        "zone_order": zone_order,
        "events": [
            {"hour": event.at_hour, "note": event.note,
             "inject": event.inject.describe() if event.inject else None}
            for event in loaded.events if event.note
        ],
        "ticks": [
            {
                "tick": tick,
                "hour": payload["hour"],
                "faults": payload["faults"],
                "nullsignal": "".join(payload["nullsignal"]),
                "baseline": "".join(payload["baseline"]),
                "truth": "".join(payload["truth"]),
            }
            for tick, payload in sorted(ticks.items())
        ],
        "scoreboard": _scoreboard_payload(score(result)),
    }


def _scoreboard_payload(board: Scoreboard) -> dict:
    return {
        "residents_at_risk": board.residents_at_risk,
        "engines": [board.baseline.as_row(), board.nullsignal.as_row()],
        "blind_spot_concentration": round(board.blind_spot_concentration, 4),
        "citywide_top_quintile_share": round(board.citywide_top_quintile_share, 4),
        "concentration_ratio": round(board.concentration_ratio, 3),
        "baseline_alarms_indiscriminately": board.baseline.alarms_indiscriminately,
        "nullsignal_is_beaten": (
            board.nullsignal.false_reassurance_rate > board.baseline.false_reassurance_rate
            and not board.baseline.alarms_indiscriminately
        ),
    }
