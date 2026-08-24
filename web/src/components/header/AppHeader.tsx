import type { Summary } from "../../lib/api";
import type { ViewMode } from "../map/ZoneMap";
import "./app-header.css";

interface AppHeaderProps {
  summary: Summary | null;
  mode: ViewMode;
  onModeChange: (mode: ViewMode) => void;
}

const MODES: { id: ViewMode; label: string; hint: string }[] = [
  { id: "nullsignal", label: "NullSignal", hint: "Risk and sufficiency as separate channels" },
  { id: "baseline", label: "Baseline", hint: "A conventional threshold dashboard" },
  { id: "disagreement", label: "Disagreement", hint: "Where the two engines differ" },
];

export function AppHeader({ summary, mode, onModeChange }: AppHeaderProps) {
  const overclaimed = summary?.reassured_by_baseline_only ?? 0;

  return (
    <header className="app-header">
      <div className="brand">
        <h1>NullSignal</h1>
        <p className="tagline">Don&rsquo;t confuse silence with safety</p>
      </div>

      <div className="headline-stat" title="Tracts a conventional dashboard calls safe that we will not">
        <span className="label">Called safe on evidence we don&rsquo;t have</span>
        <strong className="numeric">{overclaimed}</strong>
        <span className="denom numeric">of {summary?.zone_count ?? 0} tracts</span>
      </div>

      <nav className="mode-switch" aria-label="Map view">
        {MODES.map(({ id, label, hint }) => (
          <button
            key={id}
            type="button"
            title={hint}
            aria-pressed={mode === id}
            className={mode === id ? "is-active" : undefined}
            onClick={() => onModeChange(id)}
          >
            {label}
          </button>
        ))}
      </nav>
    </header>
  );
}
