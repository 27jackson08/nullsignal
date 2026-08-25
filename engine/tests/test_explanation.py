"""The explanation layer: prose that cannot invent facts."""
from __future__ import annotations

from dataclasses import fields

import pytest

from nullsignal.explain import llm, template, verifier
from nullsignal.explain.cache import ExplanationCache
from nullsignal.explain.packet import EvidencePacket, build
from nullsignal.inference import engine
from nullsignal.types import Reliability

from helpers import make_evidence, make_propensity, make_zone

PACKET = EvidencePacket(
    zone_name="Test Tract",
    borough="Bronx",
    population=6748,
    facts={"heat_index_f": 104.0, "reporting_tempo": 0.18, "residents": 6748.0},
    observations=("the transit realtime feed is answering but its content has "
                  "stopped changing",),
    gaps=("the vulnerability index is unavailable for this tract",),
    conflicts=("nws says heat_exposure=extreme but 311 says population_distress=low",),
    next_check="Call transit operations control",
    next_check_minutes=10,
)


# --- the day-7 invariant ------------------------------------------------------

def test_llm_emits_no_unsupported_numbers():
    """Every numeric token in an explanation must trace to the packet.

    A model that invents a plausible figure inside a system whose subject is
    epistemic honesty does more damage than one that says nothing, because a
    reader cannot tell an invented number from a measured one.
    """
    grounded = ("Heat index is 104F and reporting has fallen to 0.18 of this "
                "tract's usual rate. Call transit operations control, 10 minutes.")
    assert verifier.verify(grounded, PACKET).ok

    # A source name that happens to be numeric is not a figure.
    assert verifier.verify(
        grounded + " 311 reporting has fallen away.", PACKET).ok

    for invented in (
        "Roughly 4,200 residents are affected.",
        "The feed has been frozen for 68 minutes.",
        "Risk is up 37% on yesterday.",
    ):
        result = verifier.verify(grounded + " " + invented, PACKET)
        assert not result.ok, invented
        assert result.unsupported


def test_a_fabricated_number_is_structurally_impossible_in_placeholder_mode():
    """The stronger of the two guards.

    The model has no channel through which to emit a digit: it writes
    `{{field}}` and the application substitutes. Nothing to catch, because
    nothing can be produced.
    """
    skeleton = ("Heat index reached {{heat_index_f}} while reporting fell to "
                "{{reporting_tempo}} of this tract's usual rate.")
    substituted, unknown = llm._substitute(skeleton, PACKET)

    assert not unknown
    assert "104" in substituted and "0.18" in substituted
    assert verifier.verify(substituted, PACKET).ok


def test_a_placeholder_naming_a_field_we_do_not_have_is_rejected():
    _, unknown = llm._substitute("Risk is {{overall_risk_score}} today.", PACKET)
    assert unknown == {"overall_risk_score"}


# --- what the model is not allowed to see -------------------------------------

def test_the_packet_carries_no_verdict():
    """Structural guard on the whole design.

    Handing a model the conclusion and asking it to justify the conclusion
    produces fluent advocacy for whatever it was handed, including when that is
    wrong. The packet therefore has no risk score, no decision state, and no
    recommendation about safety.
    """
    names = {f.name for f in fields(EvidencePacket)}
    forbidden = {"risk", "state", "decision", "sufficiency", "verdict",
                 "posterior", "is_safe", "unresolved_harm"}
    assert not names & forbidden

    evidence = make_evidence(propensity=make_propensity(0.4))
    packet = build(evidence, engine.assess(evidence))
    serialised = packet.as_prompt_json().lower()
    for term in ("confirmed_low", "confirmed_high", "unknown", "suspected", "risk"):
        assert term not in serialised, term


# --- the floor ----------------------------------------------------------------

def test_the_template_never_returns_nothing():
    """The deterministic path is the guaranteed floor, not a degraded mode: a
    dead credential must not leave an operator without an account of why a
    tract was flagged."""
    bare = EvidencePacket(zone_name="Nowhere", borough="Queens", population=0)
    assert template.render(bare).strip()
    assert verifier.verify(template.render(PACKET), PACKET).ok


def test_generation_failure_falls_back_rather_than_raising(monkeypatch):
    monkeypatch.setattr(llm, "_credentials_available", lambda: True)
    monkeypatch.setattr(llm, "_generate", lambda packet: (_ for _ in ()).throw(
        RuntimeError("connection reset")))

    result = llm.explain(PACKET)
    assert result.source == "template"
    assert "connection reset" in result.note
    assert result.text.strip()


def test_prose_that_slips_a_bare_number_past_the_slots_is_rejected(monkeypatch):
    """The second guard exists for exactly this."""
    monkeypatch.setattr(llm, "_credentials_available", lambda: True)
    monkeypatch.setattr(llm, "_generate",
                        lambda packet: "About 4,200 residents are affected.")

    result = llm.explain(PACKET)
    assert result.source == "template"
    assert "4,200" in result.note


def test_a_clean_generation_is_used(monkeypatch):
    monkeypatch.setattr(llm, "_credentials_available", lambda: True)
    monkeypatch.setattr(llm, "_generate",
                        lambda packet: "Heat index reached {{heat_index_f}}.")

    result = llm.explain(PACKET)
    assert result.source == "generated"
    assert "104" in result.text


# --- caching ------------------------------------------------------------------

def test_identical_evidence_yields_the_identical_sentence():
    """Two accounts of one situation, differently worded, would leave an
    operator wondering which of them changed."""
    cache = ExplanationCache()
    first = cache.get(PACKET, allow_generated=False)
    second = cache.get(PACKET, allow_generated=False)
    assert first.text == second.text
    assert len(cache) == 1


def test_the_fingerprint_moves_when_the_evidence_moves():
    from dataclasses import replace
    changed = replace(PACKET, facts={**PACKET.facts, "heat_index_f": 88.0})
    assert changed.fingerprint != PACKET.fingerprint
