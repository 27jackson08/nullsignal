"""The briefing claims to print. That claim is checkable.

A work order that only exists on a screen is not an order, so the interface
says "print this order" and the runbook makes a point of it. The shell it lives
in is a fixed-height grid with independently scrolling panels, which is right
for a map filling a viewport and exactly wrong for paper: every height cap and
every scroll container becomes a guillotine.

It did. The scrolling region moved from `.record` to `.surface-scroll` when the
landmark was added for keyboard access, and the print rules kept unwinding the
old one. Measured in a browser, the order stood 4,236px tall and printed 1,032
of them -- assignments four through eight never reached paper.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web" / "src"
pytestmark = pytest.mark.skipif(not WEB.exists(), reason="web sources not present")


def stylesheets() -> dict[str, str]:
    return {str(p.relative_to(WEB)): p.read_text() for p in WEB.rglob("*.css")}


def print_blocks(text: str) -> str:
    """Every `@media print { ... }` body in one string, braces balanced."""
    out = []
    for match in re.finditer(r"@media\s+print\s*\{", text):
        depth, i = 1, match.end()
        while i < len(text) and depth:
            depth += (text[i] == "{") - (text[i] == "}")
            i += 1
        out.append(text[match.end():i - 1])
    return "\n".join(out)


def test_every_scrolling_container_is_unwound_for_paper():
    """Anything that scrolls on screen clips on paper unless it is released."""
    sheets = stylesheets()
    printed = "\n".join(print_blocks(t) for t in sheets.values())

    scrollers = set()
    for name, text in sheets.items():
        for rule in re.finditer(r"([^{}]+)\{([^}]*)\}", text):
            selector, body = rule.group(1).strip(), rule.group(2)
            if re.search(r"overflow(-y)?\s*:\s*(auto|scroll)", body):
                for part in selector.split(","):
                    cls = re.findall(r"\.([\w-]+)", part)
                    if cls:
                        scrollers.add(cls[-1])

    # Containers whose whole job is to scroll a sub-region of a page that is
    # itself scrolled: those are fine, the page-level ones are not.
    page_level = {"surface-scroll", "record"}
    for name in sorted(scrollers & page_level):
        assert re.search(rf"\.{re.escape(name)}\b[^{{}}]*\{{[^}}]*overflow", printed), (
            f".{name} scrolls on screen and is never released in @media print, "
            f"so printing it stops at one viewport"
        )


def test_the_shell_stops_being_a_fixed_height_grid_on_paper():
    printed = "\n".join(print_blocks(t) for t in stylesheets().values())

    assert re.search(r"\.app-shell\b[^{}]*\{[^}]*height\s*:\s*auto", printed), (
        "the shell keeps its 100% height on paper, which caps the document at "
        "one page regardless of what is inside it"
    )


def test_the_controls_that_cannot_be_used_on_paper_are_hidden():
    printed = "\n".join(print_blocks(t) for t in stylesheets().values())

    for control in (".app-header", ".print-order"):
        assert control in printed, f"{control} still prints"
    assert "report" in printed, "the report-back buttons still print"
