"""Deterministic explanation.

Not a degraded mode. This is the default path and the guaranteed floor: it
needs no API key, no network, and no model, so a demo cannot be broken by a
dead credential and an operator cannot be left without an account of why a
tract was flagged.

The generated path improves the prose. It is never load-bearing.
"""
from __future__ import annotations

from .packet import EvidencePacket


def render(packet: EvidencePacket) -> str:
    return " ".join(part for part in (
        _opening(packet),
        _observations(packet),
        _conflicts(packet),
        _recommendation(packet),
    ) if part)


def _opening(packet: EvidencePacket) -> str:
    if packet.gaps:
        missing = _join(packet.gaps)
        return (f"{packet.zone_name} cannot be assessed from what we have: "
                f"{missing}.")
    return f"{packet.zone_name} has a complete evidence base."


def _observations(packet: EvidencePacket) -> str:
    if not packet.observations:
        return ""
    return _sentence_case(_join(packet.observations)) + "."


def _conflicts(packet: EvidencePacket) -> str:
    if not packet.conflicts:
        return ""
    # `.lower()` on the whole sentence would flatten anything capitalised
    # inside it; only the first letter needs to change after a colon.
    if len(packet.conflicts) == 1:
        return f"Sources disagree: {_lower_first(packet.conflicts[0])}"
    return (f"{len(packet.conflicts)} source conflicts remain unresolved, "
            f"including: {_lower_first(packet.conflicts[0])}")


def _recommendation(packet: EvidencePacket) -> str:
    if not packet.next_check:
        return ""
    minutes = (f" ({packet.next_check_minutes} minutes)"
               if packet.next_check_minutes is not None else "")
    return f"The check that would resolve the most is: {packet.next_check.lower()}{minutes}."


def _join(items) -> str:
    items = list(items)
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text
