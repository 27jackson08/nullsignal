"""Scenario definitions: a timeline of world changes and instrument faults.

A scenario declares what is *true* over time and, separately, what breaks in
our ability to see it. Holding those apart is what makes the run scoreable:
ground truth is never shown to either engine, so the scoreboard measures
whether each one recovered the situation or was fooled by its feeds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import config
from ..inference.hypotheses import World
from ..types import Zone
from .injectors import FailureMode, Injection

# NWS issues heat advisories around this heat index.
DANGEROUS_HEAT_F = 100.0

# Heat that is dangerous *only if you cannot leave it*. Someone who can reach
# an air-conditioned building is fine at 93F; someone stranded in a top-floor
# apartment with no transit is not. The harm threshold depends on mobility,
# which is exactly the interaction a threshold on temperature alone cannot see.
STRANDED_HEAT_F = 92.0


@dataclass(frozen=True, slots=True)
class Event:
    at_hour: float
    heat_index_f: float | None = None
    transit_disrupted: bool | None = None
    inject: Injection | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    description: str
    duration_hours: int
    tick_hours: float
    events: tuple[Event, ...]

    @property
    def tick_count(self) -> int:
        return int(self.duration_hours / self.tick_hours) + 1

    def hour_of(self, tick: int) -> float:
        return tick * self.tick_hours


@dataclass
class WorldState:
    """Mutable ground truth as the timeline advances."""

    heat_index_f: float = 82.0
    transit_disrupted: bool = False
    active: dict[str, Injection] = field(default_factory=dict)
    injected_at: dict[str, float] = field(default_factory=dict)

    def apply(self, event: Event, hour: float) -> None:
        if event.heat_index_f is not None:
            self.heat_index_f = event.heat_index_f
        if event.transit_disrupted is not None:
            self.transit_disrupted = event.transit_disrupted
        if event.inject is not None:
            key = event.inject.describe()
            self.active[key] = event.inject
            self.injected_at.setdefault(key, hour)

    @property
    def injections(self) -> tuple[Injection, ...]:
        return tuple(self.active.values())


def true_world(state: WorldState, zone: Zone) -> World:
    """Ground truth for one zone.

    Stranding is not a citywide fact: a transit failure strands the people who
    depend on transit. In a tract where nearly everyone drives, the same outage
    on the same day is an inconvenience, and calling it a mass-casualty risk
    would make the scoreboard meaningless.
    """
    dependence = zone.pct_no_vehicle
    transit_dependent = (
        dependence is not None
        and dependence >= config.TRANSIT_DEPENDENCE_THRESHOLD
    )

    stranding_heat = state.heat_index_f >= STRANDED_HEAT_F
    if stranding_heat and state.transit_disrupted and transit_dependent:
        return World.HEAT_STRANDED
    if state.heat_index_f >= DANGEROUS_HEAT_F:
        return World.HEAT
    if state.transit_disrupted:
        return World.LOCAL_FAULT
    return World.NORMAL


# Harm level at which the scoreboard counts people as genuinely endangered.
#
# Not "anything imperfect". A signal failure inconveniences commuters who have
# cars; it does not endanger them, and counting it as harm made the whole city
# look at risk and washed every metric out. The question the scoreboard asks is
# whether anyone was actually in danger.
SERIOUS_HARM = 0.5


def is_harmful(world: World) -> bool:
    from ..inference.hypotheses import HARM_BY_WORLD
    return HARM_BY_WORLD[world] >= SERIOUS_HARM


def load(path: Path) -> Scenario:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: scenario must be a mapping")

    events = tuple(
        _parse_event(entry, path) for entry in raw.get("timeline", [])
    )
    return Scenario(
        name=raw.get("name", path.stem),
        description=raw.get("description", ""),
        duration_hours=int(raw.get("duration_hours", 12)),
        tick_hours=float(raw.get("tick_hours", 1.0)),
        events=tuple(sorted(events, key=lambda e: e.at_hour)),
    )


def _parse_event(entry: dict, path: Path) -> Event:
    if "at_hour" not in entry:
        raise ValueError(f"{path}: every timeline entry needs an at_hour")

    injection = None
    if "inject" in entry:
        spec = dict(entry["inject"])
        try:
            mode = FailureMode(spec.pop("mode"))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{path}: unknown or missing failure mode: {exc}") from exc
        injection = Injection(source=spec.pop("source"), mode=mode, **spec)

    return Event(
        at_hour=float(entry["at_hour"]),
        heat_index_f=entry.get("heat_index_f"),
        transit_disrupted=entry.get("transit_disrupted"),
        inject=injection,
        note=entry.get("note", ""),
    )


def available(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.yaml"))
