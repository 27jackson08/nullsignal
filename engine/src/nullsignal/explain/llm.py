"""Generated explanation, constrained so it cannot invent facts.

Two independent guards, because one is not enough.

**Placeholder mode.** The model never writes a number. It writes prose with
`{{field}}` slots naming values from the packet, and the application
substitutes them afterwards. A fabricated figure is not caught here -- it is
structurally impossible, because the model has no channel through which to emit
one. An unknown field name is rejected outright.

**Numeric verification.** Substituted output is checked anyway, in case a model
writes a bare number into what should have been a slot.

Anything that fails either guard falls back to the deterministic template, so
the worst case is duller prose rather than confident fiction.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from . import template, verifier
from .packet import EvidencePacket

MODEL = "claude-opus-5"
MAX_TOKENS = 2000

PLACEHOLDER = re.compile(r"\{\{([a-z0-9_]+)\}\}")

SYSTEM_PROMPT = """\
You explain evidence for a public-safety decision-support system used by city \
operators during heat emergencies.

You are given facts about one neighbourhood. Write two or three sentences \
explaining what the evidence shows and, crucially, what it does not show.

Hard rules:

1. Never write a number, in digits or in words. To refer to a measurement, \
write a placeholder naming its field: {{heat_index_f}}, {{reporting_tempo}}. \
Only field names present in `measurements` may be used.
2. Never state or imply whether the neighbourhood is safe, at risk, or in \
danger, and never recommend a level of response. Another part of the system \
decides that. You describe evidence.
3. Missing evidence is the most important thing you can report. If sources are \
unavailable or disagree, say so plainly and say what it prevents us from \
knowing.
4. Write for a duty officer at 3am. Plain sentences, no throat-clearing, no \
hedging language that obscures what is actually known.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {
            "type": "string",
            "description": "Two or three sentences, numbers written only as {{field}} placeholders.",
        }
    },
    "required": ["explanation"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class Explanation:
    text: str
    source: str          # "generated" | "template"
    note: str = ""

    @property
    def is_generated(self) -> bool:
        return self.source == "generated"


def explain(packet: EvidencePacket, *, allow_generated: bool = True) -> Explanation:
    """Best available explanation, guaranteed non-empty."""
    fallback = Explanation(template.render(packet), "template")
    if not allow_generated or not _credentials_available():
        return Explanation(fallback.text, "template", "no API credentials configured")

    try:
        raw = _generate(packet)
    except Exception as exc:  # noqa: BLE001 - never let the demo fail on this
        return Explanation(fallback.text, "template", f"generation failed: {exc}"[:160])

    substituted, unknown = _substitute(raw, packet)
    if unknown:
        return Explanation(fallback.text, "template",
                           f"unknown placeholder(s): {', '.join(sorted(unknown))}")

    checked = verifier.verify(substituted, packet)
    if not checked.ok:
        return Explanation(fallback.text, "template", checked.reason)

    return Explanation(substituted, "generated")


def _credentials_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.environ.get("ANTHROPIC_PROFILE"))


def _generate(packet: EvidencePacket) -> str:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={
            "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
        },
        messages=[{"role": "user", "content": packet.as_prompt_json()}],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("model declined to explain this packet")

    import json
    for block in response.content:
        if block.type == "text":
            return json.loads(block.text)["explanation"]
    raise RuntimeError("no text block in response")


def _substitute(text: str, packet: EvidencePacket) -> tuple[str, set[str]]:
    """Replace {{field}} with packet values; report any field we do not have."""
    unknown: set[str] = set()

    def replace(match: re.Match) -> str:
        field = match.group(1)
        if field not in packet.facts:
            unknown.add(field)
            return match.group(0)
        return _format(packet.facts[field])

    return PLACEHOLDER.sub(replace, text), unknown


def _format(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:.2f}"
