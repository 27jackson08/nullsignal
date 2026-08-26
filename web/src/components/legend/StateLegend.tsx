import { useMemo } from "react";

import { STATE_META, STATE_ORDER, type DecisionState } from "../../lib/states";
import type { Summary, ZoneCollection } from "../../lib/api";
import type { TickView } from "../../lib/playback";
import "./state-legend.css";

interface StateLegendProps {
  summary: Summary | null;
  mode: string;
  zones?: ZoneCollection | null;
  view?: TickView | null;
}

const TRUTH_LEGEND: { label: string; colour: string }[] = [
  { label: "Stranded in heat", colour: "#B33A31" },
  { label: "Dangerous heat", colour: "#8A6A1F" },
  { label: "Local fault", colour: "#2F4A63" },
  { label: "Nothing unusual", colour: "#1D2530" },
];

export function StateLegend({ summary, mode, zones, view }: StateLegendProps) {
  // During playback the counts must come from the tick being shown, not from
  // the live snapshot -- a legend that keeps reporting live totals while the
  // map moves is worse than no legend.
  const playbackCounts = useMemo(() => {
    if (!view || !zones) return null;
    const counts: Partial<Record<DecisionState, number>> = {};
    for (const feature of zones.features) {
      const state = mode === "baseline"
        ? view.baselineStateFor(feature.properties.geoid)
        : view.stateFor(feature.properties.geoid);
      if (state) counts[state] = (counts[state] ?? 0) + 1;
    }
    return counts;
  }, [view, zones, mode]);

  if (mode === "truth") {
    return (
      <aside className="state-legend" aria-label="Legend">
        <p className="label">What was actually happening</p>
        <ul>
          {TRUTH_LEGEND.map(({ label, colour }) => (
            <li key={label}>
              <span className="swatch" style={{ background: colour }} />
              <span className="name">{label}</span>
            </li>
          ))}
        </ul>
        <p className="footnote">
          Known only because the scenario generated it. Neither engine sees this.
        </p>
      </aside>
    );
  }

  if (mode === "disagreement") {
    return (
      <aside className="state-legend" aria-label="Legend">
        <p className="label">Where the engines differ</p>
        <ul>
          <li>
            <span className="swatch" style={{ background: "var(--state-confirmed-high)" }} />
            <span className="name">Baseline says safe, we don&rsquo;t</span>
          </li>
          <li>
            <span className="swatch" style={{ background: "var(--state-suspected)" }} />
            <span className="name">Other disagreement</span>
          </li>
          <li>
            <span className="swatch" style={{ background: "#1D2530" }} />
            <span className="name">Agreement</span>
          </li>
        </ul>
      </aside>
    );
  }

  const counts = playbackCounts ?? (mode === "baseline"
    ? summary?.states.baseline
    : summary?.states.nullsignal);

  return (
    <aside className="state-legend" aria-label="Legend">
      <p className="label">Risk &times; sufficiency</p>
      <ul>
        {STATE_ORDER.map((state) => {
          const meta = STATE_META[state];
          const count = counts?.[state] ?? 0;
          return (
            <li key={state} title={meta.blurb}>
              <span
                className={meta.hatched ? "swatch is-hatched" : "swatch"}
                style={{ background: meta.color }}
              />
              <span className="name">{meta.label}</span>
              <span className="count numeric">{count.toLocaleString()}</span>
            </li>
          );
        })}
      </ul>
      <p className="footnote">
        Hatching marks low sufficiency &mdash; the evidence is too thin to
        support a call, whichever way it leans.
      </p>
    </aside>
  );
}
