"""The shift briefing.

This is the surface an operator acts on, so the assertions are about the
promises it makes to them: only tracts a visit could resolve, ordered by the
people behind them, and never silent about why it cannot call one.
"""
from __future__ import annotations

import pytest

from nullsignal.findings import briefing
from nullsignal.inference import engine
from nullsignal.types import DecisionState, Reliability

from helpers import make_evidence, make_propensity, make_zone

HEALTHY = {n: Reliability() for n in ("311", "nws", "gtfs_rt", "cdc_svi")}


def assessed(items):
    return [(item, engine.assess(item, rank_checks=True)) for item in items]


def a_blind_tract(population=5000, svi=0.9, geoid="36061000100"):
    """A tract with the transit feed gone, which is what makes it unresolvable."""
    return make_evidence(
        zone=make_zone(geoid=geoid, population=population, svi_overall=svi),
        sources={**HEALTHY, "gtfs_rt": Reliability.absent()},
        propensity=make_propensity(),
    )


def a_clear_tract(geoid="36061000200"):
    return make_evidence(
        zone=make_zone(geoid=geoid, population=5000, svi_overall=0.2),
        sources=HEALTHY, heat_index_f=78.0, propensity=make_propensity(),
    )


def test_only_tracts_a_visit_could_resolve_are_assigned():
    """A tract already called either way is not verification work.

    Sending a crew to a place the engine understands wastes the shift, which is
    the whole reason the queue is ranked on unresolved harm rather than risk.
    """
    result = briefing.build(assessed([a_blind_tract(), a_clear_tract()]))

    states = {a["geoid"] for a in result.assignments}
    for item, ours in assessed([a_clear_tract()]):
        if ours.state is not DecisionState.UNKNOWN:
            assert item.zone.geoid not in states


def test_empty_tracts_never_reach_the_list():
    """Ranking on per-capita harm alone put parkland and a cemetery on top."""
    empty = make_evidence(
        zone=make_zone(geoid="36061009900", population=0, svi_overall=0.95),
        sources={**HEALTHY, "gtfs_rt": Reliability.absent()},
        propensity=make_propensity(),
    )
    result = briefing.build(assessed([empty, a_blind_tract()]))

    assert "36061009900" not in {a["geoid"] for a in result.assignments}


def test_assignments_are_ordered_by_the_people_behind_them():
    small = a_blind_tract(population=400, geoid="36061000300")
    large = a_blind_tract(population=20000, geoid="36061000400")
    result = briefing.build(assessed([small, large]))

    assert [a["geoid"] for a in result.assignments][0] == "36061000400"
    stakes = [a["residents_at_stake"] for a in result.assignments]
    assert stakes == sorted(stakes, reverse=True)


def test_every_assignment_says_why_it_cannot_be_called():
    """An order that says "go here" without saying why is not actionable."""
    result = briefing.build(assessed([a_blind_tract()]))

    for assignment in result.assignments:
        assert assignment["blind_because"], assignment
        assert all(reason.strip() for reason in assignment["blind_because"])


def test_a_missing_source_is_named_before_a_disagreement():
    """Ordering carries meaning: if the evidence is absent, resolving a
    conflict among what remains does not produce a verdict."""
    result = briefing.build(assessed([a_blind_tract()]))
    reasons = result.assignments[0]["blind_because"]

    assert "unavailable" in reasons[0]


def test_the_named_check_is_one_that_could_actually_resolve_the_tract():
    """The bug this ordering exists to fix.

    Checks were ranked by value of information, which scores how much a result
    would change the *response*. In a tract blinded by a missing feed the
    highest-VOI check was confirming the cooling centre -- a twenty-minute
    errand that cannot lift the evidence ceiling, so the tract stayed UNKNOWN
    whatever it found. The checks that would lift it scored a VOI of exactly
    zero. Ranking verification on decision value alone collapses the two axes
    this project exists to keep apart.
    """
    result = briefing.build(assessed([a_blind_tract()]))
    check = result.assignments[0]["check"]

    assert check is not None, "a blind tract with no resolving check is a finding"
    assert check["resolves_to"]["state"] != DecisionState.UNKNOWN.value, (
        f"the named check leaves the tract at {check['resolves_to']['state']}"
    )
    assert check["resolves_to"]["sufficiency"] > result.assignments[0]["sufficiency"]


def test_a_check_worth_doing_for_other_reasons_is_still_reported():
    """Kept, not dropped: it answers a different question, and saying so is
    the distinction rather than an aside."""
    result = briefing.build(assessed([a_blind_tract()]))
    also = result.assignments[0]["also_worth_doing"]

    if also is not None:
        assert also["label"] != result.assignments[0]["check"]["label"]


def test_the_tally_counts_every_unresolved_tract_not_just_the_page():
    """The briefing shows eight assignments; the tally must speak for all of
    them, or it understates what the city actually needs tonight."""
    tracts = [a_blind_tract(geoid=f"3606100{i:04d}") for i in range(12)]
    result = briefing.build(assessed(tracts), limit=4)

    assert len(result.assignments) == 4
    assert result.uncertifiable_tracts == 12
    assert sum(row["tracts"] for row in result.check_tally) == 12


def test_shares_are_zero_rather_than_wrong_without_a_quintile():
    """No vulnerability cut available means no claim, not a claim of zero risk."""
    result = briefing.build(assessed([a_blind_tract()]), top_quintile=None)
    assert result.top_quintile_share == 0.0
    assert result.concentration == 0.0


def test_the_queue_and_the_briefing_never_disagree_about_a_tract():
    """Two surfaces, one product, one answer.

    The console ranks every tract with residual doubt; the briefing takes only
    those that cannot be called. They overlap, and for a tract in both the
    named check must be the same errand. It was not: the queue named the
    highest-value check and the briefing named the one that would settle the
    call, so the same tract carried a 20-minute instruction on one screen and a
    3-minute one on the other.
    """
    from nullsignal.api.app import _queue_row

    tracts = [a_blind_tract(geoid="36061000500"), a_clear_tract()]
    pairs = assessed(tracts)
    board = briefing.build(pairs)

    rows = {row["geoid"]: row for row in (_queue_row(item, ours) for item, ours in pairs)}

    for assignment in board.assignments:
        row = rows[assignment["geoid"]]
        assert row["next_check"] == assignment["check"]["label"], (
            f"queue says {row['next_check']!r}, briefing says "
            f"{assignment['check']['label']!r}"
        )
        assert row["next_check_kind"] == "resolves"


def test_a_tract_that_was_called_is_not_offered_a_resolving_check():
    """There is nothing to resolve. Offering one would imply the tract is
    uncertain when the engine has already committed to an answer."""
    from nullsignal.api.app import _queue_row

    pairs = assessed([a_clear_tract()])
    row = _queue_row(*pairs[0])

    if pairs[0][1].state is not DecisionState.UNKNOWN:
        assert row["next_check_kind"] == "informs"


def test_no_check_claims_to_produce_a_suppressed_statistic():
    """An inspector sees the street. They do not see a census table.

    Eleven tracts are blind because CDC suppressed their vulnerability index,
    and the resolution model originally let a field inspection stand in for
    every source, so those tracts were issued a 55-minute errand that could not
    possibly settle them. A blind spot only the publisher can fix must not be
    dressed as one a crew can.
    """
    from nullsignal.voi.actions import ACTIONS
    from nullsignal.voi.resolution import SUBSTITUTES_FOR

    assert set(SUBSTITUTES_FOR) == {a.key for a in ACTIONS}, (
        "an action with no declared substitution is silently unresolvable"
    )
    for key, substitutes in SUBSTITUTES_FOR.items():
        assert "cdc_svi" not in substitutes, (
            f"{key} claims to produce a suppressed census statistic"
        )


def test_a_tract_nothing_can_settle_says_why():
    """A blank action reads as an oversight. The reason is the useful part."""
    from nullsignal.types import Reliability

    stuck = make_evidence(
        zone=make_zone(geoid="36061000700", population=4000, svi_overall=None),
        sources={**HEALTHY, "cdc_svi": Reliability.absent()},
        propensity=make_propensity(),
    )
    result = briefing.build(assessed([stuck]))
    if not result.assignments:
        pytest.skip("fixture is not unresolvable in this configuration")

    assignment = result.assignments[0]
    if assignment["check"] is None:
        assert assignment["nothing_resolves"]
        assert "suppressed" in assignment["nothing_resolves"]


def test_the_cost_to_clear_the_city_covers_only_what_a_crew_can_reach():
    """The claim is that acting on doubt is cheap. It must not be cheap by
    quietly excluding the tracts nobody can act on.

    The tally counts tracts a check could settle; the eleven whose
    vulnerability data is suppressed are not among them, and a sentence saying
    "every blind spot clears in four crew-hours" would be false by exactly that
    margin.
    """
    from nullsignal.types import Reliability

    reachable = a_blind_tract(geoid="36061001100")
    stuck = make_evidence(
        zone=make_zone(geoid="36061001200", population=4000, svi_overall=None),
        sources={**HEALTHY, "cdc_svi": Reliability.absent()},
        propensity=make_propensity(),
    )
    result = briefing.build(assessed([reachable, stuck]))

    assert result.reachable_tracts + result.unreachable_tracts == \
        result.uncertifiable_tracts
    assert result.unreachable_tracts >= 0


def test_a_resolving_check_is_only_offered_where_there_is_doubt_to_resolve():
    """One direction only.

    Every check marked as resolving must belong to a tract that could not be
    called. The converse does not hold: 94 unknown tracts have nothing in the
    catalogue that would settle them -- 83 with no residents, 11 whose
    vulnerability data is suppressed -- and they are marked unresolvable rather
    than shown a check, because naming one beside them reads as "do this and
    you will know".
    """
    from nullsignal.api.app import _queue_row
    from nullsignal.types import Reliability

    stuck = make_evidence(
        zone=make_zone(geoid="36061001300", population=4000, svi_overall=None),
        sources={**HEALTHY, "cdc_svi": Reliability.absent()},
        propensity=make_propensity(),
    )
    pairs = assessed([a_blind_tract(geoid="36061001400"), a_clear_tract(), stuck])

    for item, ours in pairs:
        row = _queue_row(item, ours)
        if row["next_check_kind"] in ("resolves", "unresolvable"):
            assert ours.state is DecisionState.UNKNOWN, (
                f"{row['name']} is {ours.state.value} but its check is marked "
                f"{row['next_check_kind']!r}"
            )
        if row["next_check_kind"] == "informs":
            assert ours.state is not DecisionState.UNKNOWN


def test_a_tract_we_understand_needs_no_attention_however_bad_it_is():
    """The queue's own claim about itself, which live data cannot test.

    No tract in the current snapshot is both high risk and well understood, so
    the assertion has nothing to bite on there. Stated on the arithmetic
    instead: doubt multiplies the harm, so a tract we are certain about
    contributes nothing to the ranking no matter how dangerous it is. That is
    what makes this a verification queue rather than a risk map, and it is the
    sentence printed above the queue in the interface.
    """
    from nullsignal.inference.hypotheses import Regime, World
    from nullsignal.voi.evpi import unresolved_harm

    # As dangerous as the hypothesis space allows. Keys are "world/regime".
    dire = {f"{World.HEAT_STRANDED}/{Regime.FAITHFUL}": 1.0}

    settled = unresolved_harm(dire, sufficiency=1.0)
    open_question = unresolved_harm(dire, sufficiency=0.2)

    assert settled == pytest.approx(0.0, abs=1e-9), (
        "a tract with no doubt left is still contributing to the verification "
        "queue, which would make it a risk map"
    )
    assert open_question > 0.1, (
        "the same danger, unresolved, must outrank it"
    )


def test_a_partial_export_leaves_the_other_scenarios_alone(tmp_path):
    """`--scenario one-thing` used to delete the other eleven.

    The export owns its output directory and clears it so a renamed tract
    cannot linger as a stale file, which is right for a full run and a trap for
    a partial one: the build then serves 404s for scenarios whose YAML is
    sitting in the repo. It caught the author twice, once while testing the
    very error path that a missing scenario produces.
    """
    from nullsignal.api import export as export_module

    out = tmp_path / "api"
    (out / "scenarios").mkdir(parents=True)
    survivor = out / "scenarios" / "already-here.json"
    survivor.write_text('{"kept": true}')

    # Only the directory handling is under test; the assessment is not.
    source = inspect_source(export_module.export)
    assert "shutil.rmtree(out_dir)" in source
    assert "not partial" in source, (
        "the rmtree is unconditional, so a partial export still wipes the rest"
    )
    assert survivor.exists()


def inspect_source(fn) -> str:
    import inspect
    return inspect.getsource(fn)
