"""Explanation cache, keyed on the packet fingerprint.

Identical evidence yields the identical sentence: a replay costs nothing, and
an operator who sees the same situation twice is not shown two differently
worded accounts of it and left wondering which changed.
"""
from __future__ import annotations

from collections import OrderedDict

from .llm import Explanation, explain
from .packet import EvidencePacket

MAX_ENTRIES = 4096


class ExplanationCache:
    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._entries: OrderedDict[str, Explanation] = OrderedDict()
        self._max_entries = max_entries

    def get(self, packet: EvidencePacket, *, allow_generated: bool = True) -> Explanation:
        key = packet.fingerprint
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            return cached

        result = explain(packet, allow_generated=allow_generated)
        self._entries[key] = result
        if len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return result

    def __len__(self) -> int:
        return len(self._entries)
