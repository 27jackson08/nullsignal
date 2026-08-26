"""Command line entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .sources.snapshot import run_snapshot
from .store import DB_FILENAME, build_store

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nullsignal")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="fetch all public sources to data/raw")
    snap.add_argument("--days", type=int, default=60,
                      help="311 lookback window in days")
    snap.add_argument("--max-requests", type=int, default=200_000)
    snap.add_argument("--skip", nargs="*", default=[],
                      choices=["tracts", "svi", "311", "weather", "transit",
                               "gtfs_static", "cooling", "air_quality",
                               "climatology", "alerts", "ems"])

    poll = sub.add_parser("poll", help="record repeated observations of volatile feeds")
    poll.add_argument("--rounds", type=int, default=1)
    poll.add_argument("--interval", type=float, default=30.0,
                      help="seconds between rounds")

    sub.add_parser("build", help="build the DuckDB store from data/raw")

    ev = sub.add_parser("eval", help="run a scenario and print the scoreboard")
    ev.add_argument("--scenario", default="heatwave-transit-silent-failure")
    ev.add_argument("--list", action="store_true", help="list available scenarios")

    export = sub.add_parser("export", help="bake the API to static JSON")
    export.add_argument("--out", default="web/public/api")
    export.add_argument("--scenario", action="append",
                        help="limit to named scenarios (repeatable)")

    serve = sub.add_parser("serve", help="run the API")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "snapshot":
        report = run_snapshot(RAW_DIR, days=args.days,
                              max_requests=args.max_requests,
                              skip=frozenset(args.skip))
        if not report.ok:
            print("\nsnapshot incomplete:", file=sys.stderr)
            for name, err in report.failures:
                print(f"  {name}: {err}", file=sys.stderr)
            return 1
        print("\nsnapshot complete")
        return 0

    if args.command == "poll":
        from .sources.poll import run_poll
        observations = run_poll(RAW_DIR, rounds=args.rounds,
                                interval_seconds=args.interval)
        print(f"\nrecorded {len(observations)} observations")
        return 0

    if args.command == "build":
        counts = build_store(RAW_DIR, DATA_DIR / DB_FILENAME)
        for table, count in counts.items():
            print(f"  {table:18} {count:>9,}")
        return 0

    if args.command == "eval":
        from .eval.report import run_evaluation
        return run_evaluation(REPO_ROOT / "scenarios", DATA_DIR / DB_FILENAME,
                              RAW_DIR, args.scenario, list_only=args.list)

    if args.command == "export":
        from .api.export import export as run_export
        out = (REPO_ROOT / args.out).resolve()
        written = run_export(out, REPO_ROOT / "scenarios",
                             scenario_names=args.scenario)
        print()
        for key, value in written.items():
            print(f"  {key:16} {value:>10,}")
        print(f"\n  written to {out}")
        return 0

    if args.command == "serve":
        import uvicorn
        uvicorn.run("nullsignal.api.app:app", host="127.0.0.1",
                    port=args.port, reload=args.reload)
        return 0

    return 1
