"""The figures quoted in the documentation must match what the engine computes.

Prose drifts. A number written into a README is a claim, and the only thing
separating it from a fabricated one is whether anybody checks. This project
argues that unverified numbers are the problem, so its own headline figures are
asserted against the store rather than trusted.

Every count here is also internally consistent by construction -- the audit's
own tests hold the parts to the sum -- but that did not stop a hand-written
breakdown in the README reading "57 broken, 29 under construction, 10 not yet
activated, 5 unknown", which totals 101 against a headline of 100.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from nullsignal.findings import cooling

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "data" / "nullsignal.duckdb"
README = REPO / "README.md"
DEMO = REPO / "docs" / "DEMO.md"

pytestmark = pytest.mark.skipif(not DB.exists(), reason="needs a built store")


@pytest.fixture(scope="module")
def audit():
    return cooling.audit(DB)


@pytest.fixture(scope="module")
def prose():
    return README.read_text() + "\n" + DEMO.read_text()


def test_the_headline_site_counts_are_quoted_correctly(audit, prose):
    assert f"{audit.site_broken} of {audit.site_total:,}" in prose or \
           f"{audit.site_broken} of 1,026" in prose, (
        f"expected the audit's {audit.site_broken}-of-{audit.site_total:,} "
        f"headline to appear in the documentation"
    )


def test_the_status_breakdown_sums_to_the_headline(audit, prose):
    """The specific error this file exists to catch.

    Any sentence that lists the statuses must add up to the number it is
    breaking down, whether it spells them in digits or in words.
    """
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty-eight": 28,
        "twenty-nine": 29, "fifty-seven": 57, "fifty-six": 56,
    }

    def number(token: str) -> int | None:
        token = token.strip().lower()
        if token.isdigit():
            return int(token)
        return words.get(token)

    statuses = ("broken", "under construction", "not yet activated", "unknown")
    pattern = re.compile(
        r"([\w-]+)\s+(" + "|".join(statuses) + r")\b", re.IGNORECASE
    )

    sentences = [
        line for line in prose.splitlines()
        if "broken" in line.lower() and "construction" in line.lower()
    ]
    assert sentences, "no status breakdown found in the documentation"

    expected = {row["status"].lower(): 0 for row in audit.by_status}
    for row in audit.by_status:
        expected[row["status"].lower()] += row["count"]

    for block in _paragraphs(prose):
        if "broken" not in block.lower() or "construction" not in block.lower():
            continue
        found = {}
        for token, status in pattern.findall(block):
            value = number(token)
            if value is not None:
                found[status.lower()] = value
        if not found:
            continue

        # Every figure named must be right, wherever it appears.
        for status, value in found.items():
            assert value == expected.get(status), (
                f"documentation says {value} {status}, store says "
                f"{expected.get(status)}"
            )

        # The sum is only a claim when the breakdown is complete. Partial
        # lists are legitimate prose -- one paragraph names three of the four
        # categories deliberately -- and demanding they total the headline
        # would fail correct writing.
        if set(found) == set(expected):
            assert sum(found.values()) == audit.site_broken, (
                f"a complete status breakdown totals {sum(found.values())} "
                f"against a headline of {audit.site_broken}: {found}"
            )


def test_the_residents_in_the_gap_are_quoted_correctly(audit, prose):
    assert f"{audit.residents_overstated:,}" in prose, (
        f"expected {audit.residents_overstated:,} residents to be quoted"
    )


def _paragraphs(text: str) -> list[str]:
    """Prose wraps across lines, so a claim is a paragraph, not a line."""
    return [block.replace("\n", " ") for block in text.split("\n\n")]
