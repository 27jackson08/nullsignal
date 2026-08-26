"""Human names for machine identifiers.

Kept in one place because these strings reach the operator through several
routes -- the evidence packet, the contradiction graph, the tract panel -- and
a source called "the weather service" in one sentence and "nws" in the next
reads as two different things.
"""
from __future__ import annotations

SOURCE_LABELS = {
    "nws": "the weather service",
    "cdc_svi": "the vulnerability index",
    "gtfs_rt": "the transit realtime feed",
    "311": "resident reports",
}


def source(name: str) -> str:
    return SOURCE_LABELS.get(name, name)
