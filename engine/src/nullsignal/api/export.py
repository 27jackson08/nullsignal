"""Bake every API response to static JSON.

A judge should be able to open a link, not clone a repository and install
Python. Everything the client asks for is derived from a committed snapshot and
never changes between requests, so it can be computed once and served as files.

The shapes written here mirror the live endpoints exactly, so the same client
code runs against either.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..eval.report import _summer_normal, snapshot_taken_at
from ..inference import pipeline
from . import app as api_app
from . import scenarios as scenario_api
from ..sim import scenario as scenario_module


def export(out_dir: Path, scenarios_dir: Path, *, scenario_names: list[str] | None = None) -> dict[str, int]:
    """Write the whole API surface under `out_dir`."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "zones").mkdir(parents=True)
    (out_dir / "scenarios").mkdir(parents=True)

    print("  assessing the city ...", flush=True)
    api_app._rebuild()

    written: dict[str, int] = {}
    written["summary"] = _write(out_dir / "summary.json", api_app.state.summary)
    written["zones"] = _write(out_dir / "zones.json",
                              {"type": "FeatureCollection",
                               "features": api_app.state.features})
    written["queue"] = _write(out_dir / "queue.json", {"zones": api_app.state.queue})

    for geoid, detail in api_app.state.detail.items():
        _write(out_dir / "zones" / f"{geoid}.json", detail)
    written["zone_detail"] = len(api_app.state.detail)

    # Worth saying out loud: without a key the prose is templated, and the
    # baked site keeps whatever mode it was exported in.
    generated = sum(1 for d in api_app.state.detail.values()
                    if d["explanation"]["source"] == "generated")
    print(f"  explanations: {generated:,} generated, "
          f"{len(api_app.state.detail) - generated:,} templated", flush=True)

    written["briefing"] = _write(out_dir / "briefing.json", api_app.state.briefing)

    from ..findings.cooling import audit as cooling_audit
    (out_dir / "findings").mkdir(exist_ok=True)
    written["cooling_finding"] = _write(out_dir / "findings" / "cooling.json",
                                        cooling_audit(api_app.DB_PATH).as_dict())

    from ..findings.reporting import analyse as reporting_analysis
    written["reporting_finding"] = _write(
        out_dir / "findings" / "reporting.json",
        reporting_analysis(api_app.DB_PATH).as_dict(),
    )

    listing = scenario_api.list_scenarios(scenarios_dir)
    written["scenario_list"] = _write(out_dir / "scenarios.json", {"scenarios": listing})

    wanted = scenario_names or [item["name"] for item in listing]
    evidence = pipeline.load_evidence(
        api_app.DB_PATH, raw_dir=api_app.RAW_DIR,
        observed_at=snapshot_taken_at(api_app.RAW_DIR, api_app.DB_PATH),
    )
    normal = _summer_normal(api_app.DB_PATH)

    for name in wanted:
        print(f"  running {name} ...", flush=True)
        payload = scenario_api.playback(scenarios_dir, name, evidence,
                                        climate_normal=normal)
        _write(out_dir / "scenarios" / f"{name}.json", payload)
    written["scenarios"] = len(wanted)

    return written


def _write(path: Path, payload) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, separators=(",", ":"))
    path.write_text(text)
    return len(text)
