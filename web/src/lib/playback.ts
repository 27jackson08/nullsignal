import type { DecisionState } from "./states";

/** Ground truth, revealed only when the operator asks for it. */
export type Truth = "normal" | "heat" | "heat_stranded" | "local_fault";

const STATE_BY_CODE: Record<string, DecisionState> = {
  L: "CONFIRMED_LOW", H: "CONFIRMED_HIGH", S: "SUSPECTED", U: "UNKNOWN",
};
const TRUTH_BY_CODE: Record<string, Truth> = {
  n: "normal", h: "heat", x: "heat_stranded", f: "local_fault",
};

export interface Tick {
  tick: number;
  hour: number;
  faults: string[];
  nullsignal: string;
  baseline: string;
  truth: string;
}

export interface Playback {
  name: string;
  description: string;
  zone_order: string[];
  events: { hour: number; note: string; inject: string | null }[];
  ticks: Tick[];
  scoreboard: {
    residents_at_risk: number;
    engines: {
      engine: string;
      false_reassurance_rate: number;
      residents_falsely_reassured: number;
      false_alarm_rate: number;
      unresolved_rate: number;
      warning_hours: number | null;
    }[];
    blind_spot_concentration: number;
    citywide_top_quintile_share: number;
    concentration_ratio: number;
    baseline_alarms_indiscriminately: boolean;
    nullsignal_is_beaten: boolean;
  };
}

/** Decoded view of one tick, indexed by tract.
 *
 *  Built once per tick rather than per tract: the payload arrives as parallel
 *  strings of state codes, and decoding them inside the render loop would redo
 *  the same 2,300 lookups on every pan. */
export class TickView {
  private readonly index: Map<string, number>;
  private readonly current: Tick;

  constructor(playback: Playback, current: Tick) {
    this.current = current;
    this.index = new Map(playback.zone_order.map((geoid, i) => [geoid, i]));
  }

  get hour() { return this.current.hour; }
  get faults() { return this.current.faults; }

  stateFor(geoid: string): DecisionState | null {
    const at = this.index.get(geoid);
    return at === undefined ? null : STATE_BY_CODE[this.current.nullsignal[at]] ?? null;
  }

  baselineStateFor(geoid: string): DecisionState | null {
    const at = this.index.get(geoid);
    return at === undefined ? null : STATE_BY_CODE[this.current.baseline[at]] ?? null;
  }

  truthFor(geoid: string): Truth | null {
    const at = this.index.get(geoid);
    return at === undefined ? null : TRUTH_BY_CODE[this.current.truth[at]] ?? null;
  }
}

export async function fetchPlayback(base: string, name: string): Promise<Playback> {
  const response = await fetch(`${base}/api/scenarios/${name}`);
  if (!response.ok) throw new Error(`scenario ${name}: ${response.status}`);
  return response.json() as Promise<Playback>;
}
