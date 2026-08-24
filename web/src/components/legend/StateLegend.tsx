import { STATE_META, STATE_ORDER } from "../../lib/states";
import type { Summary } from "../../lib/api";
import "./state-legend.css";

interface StateLegendProps {
  summary: Summary | null;
  mode: string;
}

export function StateLegend({ summary, mode }: StateLegendProps) {
  if (mode === "disagreement") {
    return (
      <aside className="state-legend" aria-label="Legend">
        <p className="label">Where the engines differ</p>
        <ul>
          <li>
            <span className="swatch" style={{ background: "#D9564C" }} />
            <span className="name">Baseline says safe, we don&rsquo;t</span>
          </li>
          <li>
            <span className="swatch" style={{ background: "#D99A2B" }} />
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

  const counts = mode === "baseline"
    ? summary?.states.baseline
    : summary?.states.nullsignal;

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
