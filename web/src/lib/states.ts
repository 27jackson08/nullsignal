/** The 2x2. Risk maps to hue, sufficiency maps to texture; the two channels
 *  are never merged, because collapsing them onto one green-to-red ramp is the
 *  exact failure this product exists to correct. */

export type DecisionState =
  | "UNKNOWN"
  | "CONFIRMED_LOW"
  | "SUSPECTED"
  | "CONFIRMED_HIGH";

export interface StateMeta {
  label: string;
  color: string;
  /** Low sufficiency renders hatched: the visual signature of missing signal. */
  hatched: boolean;
  blurb: string;
}

export const STATE_META: Record<DecisionState, StateMeta> = {
  CONFIRMED_LOW: {
    label: "Confirmed low",
    color: "#2E9E7E",
    hatched: false,
    blurb: "Quiet, and we can see well enough to say so.",
  },
  CONFIRMED_HIGH: {
    label: "Confirmed high",
    color: "#D9564C",
    hatched: false,
    blurb: "Corroborated danger. Act now.",
  },
  SUSPECTED: {
    label: "Suspected",
    color: "#D99A2B",
    hatched: true,
    blurb: "Signs of harm, but the evidence base is thin or conflicting.",
  },
  UNKNOWN: {
    label: "Unknown",
    color: "#59646F",
    hatched: true,
    blurb: "Not enough trustworthy evidence to call it either way.",
  },
};

export const STATE_ORDER: DecisionState[] = [
  "CONFIRMED_HIGH",
  "SUSPECTED",
  "UNKNOWN",
  "CONFIRMED_LOW",
];

/** Only one state tells an operator a place is fine. */
export const isReassuring = (state: DecisionState) => state === "CONFIRMED_LOW";
