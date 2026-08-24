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

    evidence = pipeline.load_evidence(db_path, raw_dir=raw_dir)
    result = simrun.run(loaded, evidence)
    _render(score(result), loaded.description.strip())
    return 0


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
          f"{'false alarm':>13} {'warning':>9}")

    for engine in (board.baseline, board.nullsignal):
        warning = (f"{engine.warning_hours:.0f}h"
                   if engine.warning_hours is not None else "none")
        print(f"  {engine.name:12} {engine.false_reassurance_rate:>18.1%} "
              f"{engine.residents_falsely_reassured:>12,} "
              f"{engine.false_alarm_rate:>12.1%} {warning:>9}")

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
