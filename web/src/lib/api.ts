import type { FeatureCollection, MultiPolygon } from "geojson";

import type { DecisionState } from "./states";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

/**
 * A static build serves pre-computed JSON instead of calling the engine.
 *
 * Every response is derived from a committed snapshot and never varies between
 * requests, so the whole API can be baked to files (`nullsignal export`) and
 * hosted anywhere. Same client code, no backend.
 */
const IS_STATIC = import.meta.env.VITE_STATIC === "1";

/**
 * Map a live endpoint onto the file the export wrote for it.
 *
 * The export mirrors the route tree, so every path becomes itself plus
 * `.json`. Query strings are dropped: the only one in use is the queue limit,
 * and the export writes the full queue for the client to slice.
 */
function staticPath(path: string): string {
  const [route] = path.split("?");
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  return `${base}${route}.json`;
}

export interface ZoneProperties {
  geoid: string;
  name: string;
  borough: string;
  population: number;
  state: DecisionState;
  baseline_state: DecisionState;
  risk: number;
  sufficiency: number;
  disagrees: boolean;
}

export interface ZoneDetail {
  geoid: string;
  name: string;
  borough: string;
  population: number;
  state: DecisionState;
  baseline_state: DecisionState;
  risk: number;
  sufficiency: {
    score: number;
    measured: Record<string, number>;
    unmeasured: string[];
    ceiling: number;
  };
  evidence: {
    heat_index_f: number | null;
    report_count: number;
    latest_report_at: string | null;
    transit_feed_age_seconds: number | null;
    missing_critical_sources: string[];
  };
  source_reliability: Record<string, SourceReliability>;
  reporting: {
    estimated: boolean;
    note?: string;
    index?: number;
    confidence?: number;
    evidential_weight?: number;
    categories?: number;
    total_reports?: number;
  };
  contradictions: string[];
  explanation: {
    text: string;
    source: "generated" | "template";
    note: string;
    packet_fingerprint: string;
  };
  unseen_danger: number;
  unresolved_harm: number;
  decision: string;
  posterior: { hypothesis: string; probability: number }[];
  recommended_checks: {
    key: string; label: string; value: number; value_per_cost: number;
    cost: number; latency_minutes: number; detail: string;
  }[];
  heat_relief: {
    reachable: number | null;
    listed: number | null;
    overstated: number | null;
  };
  vulnerability: {
    svi_overall: number | null;
    pct_no_vehicle: number | null;
    pct_age_65_plus: number | null;
    multiplier: number;
  };
}

export type ZoneCollection = FeatureCollection<MultiPolygon, ZoneProperties>;

export interface SourceReliability {
  score: number;
  freshness: number;
  coverage: number;
  liveness: number;
  is_critical: boolean;
}

export interface Detector {
  name: string;
  assessable: boolean;
  fired: boolean;
  confidence_dead: number;
  detail: string;
}

export interface FeedHealth {
  source_id: string;
  liveness: number;
  poll_count: number;
  worst_member: string | null;
  detectors: Detector[];
}

export interface Summary {
  zone_count: number;
  states: {
    nullsignal: Partial<Record<DecisionState, number>>;
    baseline: Partial<Record<DecisionState, number>>;
  };
  disagreements: number;
  reassured_by_baseline_only: number;
  feeds: FeedHealth[];
  snapshot: {
    available: boolean;
    snapshot_at?: string;
    sources?: { source_id: string; fetched_at: string; content_hash: string; bytes: number }[];
    failures?: { source: string; error: string }[];
  };
}

export async function apiGet<T>(path: string): Promise<T> {
  const url = IS_STATIC ? staticPath(path) : `${API_BASE}${path}`;
  const response = await fetch(url);
  if (!response.ok) {
    // Surfaced to the user rather than swallowed: a blank map with no
    // explanation is precisely the failure mode this project is about.
    throw new Error(`${path} returned ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const fetchZones = () =>
  apiGet<ZoneCollection>("/api/zones");
export const fetchSummary = () => apiGet<Summary>("/api/summary");
export const fetchZoneDetail = (geoid: string) =>
  apiGet<ZoneDetail>(`/api/zones/${geoid}`);

export interface ScenarioSummary {
  name: string;
  description: string;
  duration_hours: number;
  event_count: number;
}

export const fetchScenarios = () =>
  apiGet<{ scenarios: ScenarioSummary[] }>("/api/scenarios").then((r) => r.scenarios);

export interface QueueEntry {
  geoid: string;
  name: string;
  borough: string;
  population: number;
  state: DecisionState;
  unresolved_harm: number;
  residents_at_stake: number;
  risk: number;
  sufficiency: number;
  decision: string;
  next_check: string | null;
  next_check_minutes: number | null;
}

// The static export writes the whole ranking, so the limit is applied here
// rather than by the server. Slicing twice is harmless.
export const fetchQueue = (limit = 8) =>
  apiGet<{ zones: QueueEntry[] }>(`/api/queue?limit=${limit}`)
    .then((r) => r.zones.slice(0, limit));


export interface CoolingFinding {
  sites: {
    total: number;
    working: number;
    not_working: number;
    by_status: { kind: string; status: string; count: number }[];
    by_borough: { borough: string; not_working: number }[];
  };
  impact: {
    tracts_overstated: number;
    residents_overstated: number;
    residents_without_relief: number;
  };
  equity: {
    overstated_top_quintile_share: number;
    citywide_top_quintile_share: number;
    concentration: number;
  };
  worst: {
    geoid: string; name: string; borough: string; population: number;
    listed: number; working: number; gap: number; svi_overall: number | null;
  }[];
}

export const fetchCoolingFinding = () =>
  apiGet<CoolingFinding>("/api/findings/cooling");


export interface Briefing {
  issued_at: string | null;
  situation: {
    uncertifiable_tracts: number;
    uncertifiable_residents: number;
    top_quintile_share: number;
    citywide_top_quintile_share: number;
    concentration: number;
  };
  assignments: {
    rank: number; geoid: string; name: string; borough: string;
    population: number; residents_at_stake: number;
    blind_because: string[];
    check: { label: string; minutes: number; detail: string } | null;
  }[];
  check_tally: { check: string; tracts: number; residents: number; minutes: number }[];
  residents_on_the_list: number;
}

export const fetchBriefing = () => apiGet<Briefing>("/api/briefing");
