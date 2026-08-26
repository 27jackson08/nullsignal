"""Human-readable scoreboard output."""
from __future__ import annotations

import sys
from pathlib import Path

from ..inference import pipeline
from ..sim import run as simrun
from ..sim import scenario as scenario_module
from .scoreboard import Scoreboard, score

RULE = "-" * 78


def run_evaluation(
    scenarios_dir: Path,
    db_path: Path,
    raw_dir: Path,
    name: str,
    *,
    list_only: bool = False,
) -> int:
    available = scenario_module.available(scenarios_dir)
    if list_only:
        for path in available:
            loaded = scenario_module.load(path)
            print(f"  {loaded.name:42} {loaded.duration_hours}h  {len(loaded.events)} events")
        return 0

    path = scenarios_dir / f"{name}.yaml"
    if not path.exists():
        print(f"no scenario named {name!r}. Available:", file=sys.stderr)
        for candidate in available:
            print(f"  {candidate.stem}", file=sys.stderr)
        return 1

    loaded = scenario_module.load(path)
    print(f"running {loaded.name} ({loaded.duration_hours}h)...", flush=True)

    # Anchored to the moment the snapshot was taken, not to the moment the
    # evaluation runs. Otherwise the scoreboard drifts as the fixtures age --
    # 311 freshness decays against wall clock, more tracts fall to UNKNOWN, and
    # a number that is supposed to be a property of the scenario becomes a
    # property of the calendar. A scoreboard you cannot re-derive is an
    # anecdote.
    evidence = pipeline.load_evidence(
        db_path, raw_dir=raw_dir, observed_at=snapshot_taken_at(raw_dir, db_path))
    result = simrun.run(loaded, evidence, _summer_normal(db_path))
    _render(score(result), loaded.description.strip())
    return 0


def snapshot_taken_at(raw_dir: Path, db_path: Path):
    """When the committed fixtures were captured.

    The manifest records it; the newest 311 record is the fallback for a
    snapshot assembled without one.
    """
    from datetime import UTC, datetime

    from ..sources.snapshot import load_manifest

    try:
        stamp = load_manifest(raw_dir).get("snapshot_at")
        if stamp:
            parsed = datetime.fromisoformat(stamp)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (FileNotFoundError, ValueError):
        pass

    from ..store import connect

    con = connect(db_path, read_only=True)
    try:
        row = con.execute("SELECT MAX(created_at) FROM service_requests").fetchone()
    except Exception:  # noqa: BLE001
        return None
    finally:
        con.close()
    if not row or row[0] is None:
        return None
    return row[0] if row[0].tzinfo else row[0].replace(tzinfo=UTC)


def _summer_normal(db_path: Path) -> dict | None:
    """The normal for a representative summer day.

    Scenarios are dated relative to their own start rather than to the wall
    clock, so they are scored against a July normal instead of whatever day the
    evaluation happens to run on.
    """
    from ..store import connect

    con = connect(db_path, read_only=True)
    try:
        row = con.execute(
            "SELECT mean_max_f, stdev_f, samples FROM climate_normals "
            "WHERE day_of_year = 199").fetchone()
    except Exception:  # noqa: BLE001
        return None
    finally:
        con.close()
    return ({"mean_max_f": row[0], "stdev_f": row[1], "samples": row[2]}
            if row else None)


def _render(board: Scoreboard, description: str) -> None:
    print()
    print(RULE)
    print(f"  {board.scenario}")
    print(RULE)
    if description:
        for line in description.splitlines():
            print(f"  {line.strip()}")
        print()

    print(f"  Residents in genuinely endangered tracts: {board.residents_at_risk:,}")
    print()
    print(f"  {'':12} {'false reassurance':>19} {'residents':>12} "
          f"{'false alarm':>13} {'unresolved':>12} {'warning':>9}")

    for engine in (board.baseline, board.nullsignal):
        warning = (f"{engine.warning_hours:.0f}h"
                   if engine.warning_hours is not None else "none")
        print(f"  {engine.name:12} {engine.false_reassurance_rate:>18.1%} "
              f"{engine.residents_falsely_reassured:>12,} "
              f"{engine.false_alarm_rate:>12.1%} {engine.unresolved_rate:>11.1%} "
              f"{warning:>9}")

    print()
    print("  false alarm = claimed danger while nothing was wrong.")
    print("  unresolved  = declined to confirm safety. Not the same failure, so")
    print("                not folded into the same number.")

    for engine in (board.baseline, board.nullsignal):
        if engine.alarms_indiscriminately:
            print(f"  Note: {engine.name} scores well on false reassurance only by "
                  f"alarming\n        {engine.false_alarm_rate:.0%} of the time when "
                  f"nothing is wrong. A stopped clock.")
            print()

    if board.nullsignal.false_reassurance_rate > board.baseline.false_reassurance_rate \
            and not board.baseline.alarms_indiscriminately:
        print("  Note: NullSignal is BEATEN in this scenario. Reported rather than")
        print("        hidden - a scoreboard that only shows wins is a slide, not a")
        print("        measurement.")
        print()

    print("  Who is standing in the blind spots")
    print(f"    {board.blind_spot_concentration:.1%} of residents the conventional "
          f"dashboard kept calling safe")
    print(f"    are in the most vulnerable quintile, against "
          f"{board.citywide_top_quintile_share:.1%} citywide "
          f"({board.concentration_ratio:.2f}x).")
    print()

    averted = (board.baseline.residents_falsely_reassured
               - board.nullsignal.residents_falsely_reassured)
    if averted > 0:
        print(f"  {averted:,} residents were not written off as safe.")
    print(RULE)
