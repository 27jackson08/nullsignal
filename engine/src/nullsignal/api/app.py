"""FastAPI surface.

Assessments are computed once at startup and held in memory: the snapshot is
immutable, so recomputing per request would burn CPU to produce identical
answers. A scenario replay (day 5) will recompute per tick instead.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..eval import baseline
from ..explain.cache import ExplanationCache
from ..explain.packet import build as build_packet
from ..inference import engine, pipeline
from ..reliability.feeds import FeedHealth, assess_feeds
from . import scenarios as scenario_api
from .security import SecurityHeadersMiddleware
from ..sources.snapshot import load_manifest
from ..store import DB_FILENAME, connect
from ..types import ZoneAssessment

REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = REPO_ROOT / "data"
SCENARIOS_DIR = REPO_ROOT / "scenarios"
DB_PATH = DATA_DIR / DB_FILENAME
RAW_DIR = DATA_DIR / "raw"


@dataclass
class EngineState:
    """Precomputed view of one snapshot."""

    features: list[dict]
    detail: dict[str, dict]
    summary: dict
    queue: list[dict]
    briefing: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    playback_cache: dict = field(default_factory=dict)
    explanations: ExplanationCache = field(default_factory=ExplanationCache)


state = EngineState(features=[], detail={}, summary={}, queue=[])


@asynccontextmanager
async def lifespan(_: FastAPI):
    _rebuild()
    yield


app = FastAPI(title="NullSignal", version="0.1.0", lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Vite dev server and `vite preview`, on both loopback spellings.
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _rebuild() -> None:
    """Assess the whole city once and cache every view of the result."""
    if not DB_PATH.exists():
        raise RuntimeError(
            f"no store at {DB_PATH}. Run: uv run nullsignal snapshot && uv run nullsignal build"
        )

    evidence = pipeline.load_evidence(DB_PATH, raw_dir=RAW_DIR)
    feed_health = assess_feeds(RAW_DIR)
    geometry = _load_geometry()
    # Calibrated against this snapshot so the comparison is against a dashboard
    # someone would actually run, not one rigged to fail.
    thresholds = baseline.calibrate(evidence)

    assessed = [
        (item, engine.assess(item), baseline.assess(item, thresholds))
        for item in evidence
    ]

    state.features = [
        _feature(item, ours, theirs, geometry[item.zone.geoid])
        for item, ours, theirs in assessed
        if item.zone.geoid in geometry
    ]
    state.detail = {
        item.zone.geoid: _detail(item, ours, theirs)
        for item, ours, theirs in assessed
    }
    # Ranked by expected residents at stake: unresolved harm per capita times
    # the population it falls on. Unresolved harm alone is monotone in
    # vulnerability and doubt (see voi/evpi.unresolved_harm) but says nothing
    # about how many people are standing there.
    state.queue = sorted(
        (_queue_row(item, ours) for item, ours, _ in assessed),
        key=lambda row: -row["residents_at_stake"],
    )
    state.evidence = evidence
    state.playback_cache = {}
    state.summary = _summary(assessed, feed_health)

    from ..eval.report import snapshot_taken_at
    from ..findings.briefing import build as build_briefing
    taken = snapshot_taken_at(RAW_DIR, DB_PATH)
    state.briefing = build_briefing(
        [(item, ours) for item, ours, _ in assessed],
        issued_at=None if taken is None else taken.isoformat(),
        top_quintile=_vulnerability_quintile(evidence),
    ).as_dict()


def _vulnerability_quintile(evidence) -> float | None:
    """The 80th percentile of tract vulnerability, over tracts that have one.

    Suppressed tracts are excluded from the cut rather than treated as zero:
    counting them as least-vulnerable would move the threshold and quietly
    understate every share measured against it.
    """
    from statistics import quantiles
    values = sorted(
        item.zone.svi_overall for item in evidence
        if item.zone.svi_overall is not None
    )
    if len(values) < 5:
        return None
    return quantiles(values, n=5, method="inclusive")[3]


def _feature(item, ours: ZoneAssessment, theirs: ZoneAssessment, shape: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": shape,
        "properties": {
            "geoid": item.zone.geoid,
            "name": item.zone.name,
            "borough": item.zone.borough,
            "population": item.zone.population,
            "state": ours.state.value,
            "baseline_state": theirs.state.value,
            "risk": round(ours.risk, 4),
            "sufficiency": round(ours.sufficiency.score, 4),
            "disagrees": ours.state.value != theirs.state.value,
        },
    }


def _queue_row(item, ours: ZoneAssessment) -> dict:
    check = ours.recommended_checks[0] if ours.recommended_checks else None
    return {
        "geoid": item.zone.geoid,
        # Per-capita harm times the people it lands on. Ranking on the
        # per-capita figure alone put empty parks and a cemetery at the top of
        # the operator's queue: a tract with nobody in it can be just as
        # unresolved as a dense one, and the arithmetic could not tell them
        # apart.
        "residents_at_stake": round(ours.unresolved_harm * item.zone.population, 2),
        "name": item.zone.name,
        "borough": item.zone.borough,
        "population": item.zone.population,
        "state": ours.state.value,
        "unresolved_harm": ours.unresolved_harm,
        "unseen_danger": ours.unseen_danger,
        "risk": round(ours.risk, 4),
        "sufficiency": round(ours.sufficiency.score, 4),
        "decision": ours.current_decision,
        "next_check": check.label if check else None,
        "next_check_minutes": check.latency_minutes if check else None,
    }


def _summary(assessed: list, feed_health: dict[str, FeedHealth]) -> dict:
    counts: dict[str, dict[str, int]] = {"nullsignal": {}, "baseline": {}}
    disagreements = 0
    reassured_by_baseline_only = 0

    for _, ours, theirs in assessed:
        counts["nullsignal"][ours.state.value] = \
            counts["nullsignal"].get(ours.state.value, 0) + 1
        counts["baseline"][theirs.state.value] = \
            counts["baseline"].get(theirs.state.value, 0) + 1
        if ours.state is not theirs.state:
            disagreements += 1
        if theirs.state.is_reassuring and not ours.state.is_reassuring:
            reassured_by_baseline_only += 1

    return {
        "zone_count": len(assessed),
        "states": counts,
        "disagreements": disagreements,
        "reassured_by_baseline_only": reassured_by_baseline_only,
        "snapshot": _manifest_summary(),
        "feeds": _feed_summary(feed_health),
    }


def _feed_summary(feed_health: dict[str, FeedHealth]) -> list[dict]:
    """Per-source liveness, including which detectors could not run.

    "Not checked" is reported alongside "checked and fine", because a system
    premised on the difference cannot collapse it in its own status panel.
    """
    return [
        {
            "source_id": source_id,
            "liveness": round(health.score, 4),
            "poll_count": health.poll_count,
            "worst_member": health.worst_member,
            "detectors": [
                {
                    "name": detector.name,
                    "assessable": detector.assessable,
                    "fired": detector.fired,
                    "confidence_dead": round(detector.confidence_dead, 4),
                    "detail": detector.detail,
                }
                for detector in health.liveness.detectors
            ],
        }
        for source_id, health in sorted(feed_health.items())
    ]


def _detail(item, ours: ZoneAssessment, theirs: ZoneAssessment) -> dict:
    suff = ours.sufficiency
    return {
        "geoid": item.zone.geoid,
        "name": item.zone.name,
        "borough": item.zone.borough,
        "population": item.zone.population,
        "state": ours.state.value,
        "baseline_state": theirs.state.value,
        "risk": round(ours.risk, 4),
        "unseen_danger": ours.unseen_danger,
        "unresolved_harm": ours.unresolved_harm,
        "decision": ours.current_decision,
        "posterior": sorted(
            ({"hypothesis": k, "probability": round(v, 4)}
             for k, v in ours.posterior.items()),
            key=lambda row: -row["probability"],
        )[:5],
        "recommended_checks": [
            {"key": c.key, "label": c.label, "value": c.value,
             "value_per_cost": c.value_per_cost, "cost": c.cost,
             "latency_minutes": c.latency_minutes, "detail": c.detail}
            for c in ours.recommended_checks[:3]
        ],
        "sufficiency": {
            "score": round(suff.score, 4),
            "measured": {k: round(v, 4) for k, v in suff.measured_terms.items()},
            "unmeasured": [
                k for k in ("entropy", "coverage", "contradiction", "staleness")
                if k not in suff.measured_terms
            ],
            "ceiling": suff.ceiling,
        },
        "evidence": {
            "heat_index_f": round(item.heat_index_f, 1) if item.heat_index_f else None,
            "report_count": item.report_count,
            "latest_report_at": item.latest_report_at.isoformat()
            if item.latest_report_at else None,
            "transit_feed_age_seconds": item.transit_feed_age_seconds,
            "missing_critical_sources": list(item.missing_critical_sources),
        },
        "source_reliability": {
            name: {
                "score": round(rel.score, 4),
                "freshness": round(rel.freshness, 4),
                "coverage": round(rel.coverage, 4),
                "liveness": round(rel.liveness, 4),
                "is_critical": name in item.critical_sources,
            }
            for name, rel in item.source_reliability.items()
        },
        "explanation": _explanation(item, ours),
        "reporting": _reporting_detail(item),
        "contradictions": list(ours.contradictions),
        "heat_relief": {
            "reachable": (round(item.zone.cooling_working, 3)
                          if item.zone.cooling_working is not None else None),
            "listed": (round(item.zone.cooling_listed, 3)
                       if item.zone.cooling_listed is not None else None),
            "overstated": (round(item.zone.unreachable_relief, 3)
                           if item.zone.unreachable_relief is not None else None),
        },
        "vulnerability": {
            "svi_overall": item.zone.svi_overall,
            "pct_no_vehicle": item.zone.pct_no_vehicle,
            "pct_age_65_plus": item.zone.pct_age_65_plus,
            "multiplier": round(item.zone.vulnerability_multiplier, 3),
        },
    }


def _explanation(item, assessment) -> dict:
    """Prose account of the evidence, generated or deterministic.

    Built from a packet that deliberately excludes the verdict: the language
    layer describes what the evidence is, never what it means.
    """
    packet = build_packet(item, assessment)
    result = state.explanations.get(packet)
    return {
        "text": result.text,
        "source": result.source,
        "note": result.note,
        "packet_fingerprint": packet.fingerprint,
    }


def _reporting_detail(item) -> dict:
    """How readily this tract reports, and what that does to its silence.

    Surfaced because it changes the reading of zero complaints: the same
    silence means something different in a tract that calls constantly and one
    that never does.
    """
    propensity = item.propensity
    if propensity is None or not propensity.is_estimated:
        return {"estimated": False,
                "note": "too few reporting categories to estimate"}
    return {
        "estimated": True,
        "index": round(propensity.index, 3),
        "confidence": round(propensity.confidence, 3),
        "evidential_weight": round(propensity.evidential_weight, 3),
        "categories": propensity.category_count,
        "total_reports": propensity.total_reports,
    }


def _load_geometry() -> dict[str, dict]:
    con = connect(DB_PATH, read_only=True)
    try:
        rows = con.execute(
            "SELECT geoid, geom_simplified FROM zones WHERE geom_simplified IS NOT NULL"
        ).fetchall()
    finally:
        con.close()
    return {geoid: json.loads(shape) for geoid, shape in rows}


def _manifest_summary() -> dict:
    try:
        manifest = load_manifest(RAW_DIR)
    except FileNotFoundError:
        return {"available": False}
    return {
        "available": True,
        "snapshot_at": manifest.get("snapshot_at"),
        "sources": [
            {"source_id": s["source_id"], "fetched_at": s["fetched_at"],
             "content_hash": s["content_hash"], "bytes": s["byte_count"]}
            for s in manifest.get("sources", [])
        ],
        "failures": manifest.get("failures", []),
    }


@app.get("/api/briefing")
def get_briefing() -> dict:
    """Tonight's work order: where to go, why, and what to do there."""
    return state.briefing


@app.get("/api/findings/reporting")
def get_reporting_finding() -> dict:
    """What 311 can and cannot tell you. Real data, no simulation involved."""
    from ..findings.reporting import analyse
    return analyse(DB_PATH).as_dict()


@app.get("/api/findings/cooling")
def get_cooling_finding() -> dict:
    """The heat-relief audit. Real data, no simulation involved."""
    from ..findings.cooling import audit
    return audit(DB_PATH).as_dict()


@app.get("/api/summary")
def get_summary() -> dict:
    return state.summary


@app.get("/api/scenarios")
def get_scenarios() -> dict:
    return {"scenarios": scenario_api.list_scenarios(SCENARIOS_DIR)}


@app.get("/api/scenarios/{name}")
def get_scenario(name: str) -> dict:
    """Run a scenario and return it as a scrubbable timeline.

    Cached after the first request: a run takes seconds, and the client needs
    to seek through it freely once it has it.
    """
    if name in state.playback_cache:
        return state.playback_cache[name]
    try:
        from ..eval.report import _summer_normal
        payload = scenario_api.playback(SCENARIOS_DIR, name, state.evidence,
                                        climate_normal=_summer_normal(DB_PATH))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"no scenario named {name!r}") from None
    state.playback_cache[name] = payload
    return payload


@app.get("/api/queue")
def get_queue(limit: int = 25) -> dict:
    """Zones ordered by how much unresolved harm is riding on them."""
    return {"zones": state.queue[:max(1, min(limit, 200))]}


@app.get("/api/zones")
def get_zones() -> dict:
    return {"type": "FeatureCollection", "features": state.features}


@app.get("/api/zones/{geoid}")
def get_zone(geoid: str) -> dict:
    detail = state.detail.get(geoid)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown zone {geoid}")
    return detail
