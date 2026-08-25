import type { FeatureCollection, MultiPolygon } from "geojson";

import type { DecisionState } from "./states";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

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

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    // Surfaced to the user rather than swallowed: a blank map with no
    // explanation is precisely the failure mode this project is about.
    throw new Error(`${path} returned ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const fetchZones = () =>
  getJson<ZoneCollection>("/api/zones");
export const fetchSummary = () => getJson<Summary>("/api/summary");
export const fetchZoneDetail = (geoid: string) =>
  getJson<ZoneDetail>(`/api/zones/${geoid}`);

export interface ScenarioSummary {
  name: string;
  description: string;
  duration_hours: number;
  event_count: number;
}

export const fetchScenarios = () =>
  getJson<{ scenarios: ScenarioSummary[] }>("/api/scenarios").then((r) => r.scenarios);

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

export const fetchQueue = (limit = 8) =>
  getJson<{ zones: QueueEntry[] }>(`/api/queue?limit=${limit}`).then((r) => r.zones);
