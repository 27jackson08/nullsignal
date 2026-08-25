"""Numeric verification of generated prose.

Every number in an explanation must trace back to the packet it was generated
from. A model that invents a plausible figure inside a system whose subject is
epistemic honesty does more damage than one that says nothing, and a reader has
no way to tell an invented number from a measured one.

The check is deliberately blunt: extract every numeric token, and reject the
whole explanation if any of them is not in the packet. Rejection falls back to
the deterministic template, so the failure mode is duller prose rather than
confident fiction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .packet import EvidencePacket

# Numbers with optional thousands separators, decimals, and a trailing unit.
NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(%|x|F|C|min|h|hours?|minutes?)?",
                    re.IGNORECASE)

# Rounding slack, so "1.84 times" matches a stored 1.8351.
TOLERANCE = 0.011

# Ordinals and small counts that are prose rather than measurement.
PROSE_NUMBERS = frozenset({0.0, 1.0, 2.0, 3.0, 24.0, 48.0, 60.0, 100.0})


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    unsupported: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        if self.ok:
            return "every figure traces to the evidence packet"
        return "unsupported figures: " + ", ".join(self.unsupported)


def allowed_values(packet: EvidencePacket) -> set[float]:
    """Every number the prose is permitted to contain."""
    allowed: set[float] = set(PROSE_NUMBERS)

    for value in packet.facts.values():
        allowed.update(_variants(value))

    # Numbers already present in the packet's own prose are grounded by
    # definition -- they are the evidence, quoted. Without this the checker
    # rejects a source's *name*: "311 says population_distress=low" reads as an
    # unsupported figure of three hundred and eleven.
    for text in (*packet.observations, *packet.gaps, *packet.conflicts,
                 packet.next_check, packet.zone_name):
        for match in NUMBER.finditer(text):
            try:
                allowed.update(_variants(float(match.group(1).replace(",", ""))))
            except ValueError:
                continue

    # Counts of the lists themselves: "two sources disagree" is a fact about
    # the packet even though no field holds the number two.
    allowed.update(_variants(float(len(packet.observations))))
    allowed.update(_variants(float(len(packet.gaps))))
    allowed.update(_variants(float(len(packet.conflicts))))

    if packet.next_check_minutes is not None:
        allowed.update(_variants(float(packet.next_check_minutes)))

    return allowed


def verify(text: str, packet: EvidencePacket) -> Verdict:
    permitted = allowed_values(packet)
    unsupported: list[str] = []

    for match in NUMBER.finditer(text):
        raw, unit = match.group(1), (match.group(2) or "").lower()
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue

        candidates = {value}
        if unit == "%":
            # A model may write a share either way round; both readings must
            # be supported by the packet, not just one.
            candidates.add(value / 100.0)

        if not any(_is_allowed(candidate, permitted) for candidate in candidates):
            unsupported.append(match.group(0).strip())

    return Verdict(ok=not unsupported, unsupported=tuple(unsupported))


def _variants(value: float) -> set[float]:
    """A value and the roundings a writer might reasonably use for it."""
    return {value, round(value), round(value, 1), round(value, 2),
            float(int(value)), value * 100.0, round(value * 100.0)}


def _is_allowed(value: float, permitted: set[float]) -> bool:
    return any(abs(value - candidate) <= TOLERANCE for candidate in permitted)
