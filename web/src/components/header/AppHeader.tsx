import type { Summary } from "../../lib/api";
import type { ViewMode } from "../map/ZoneMap";
import "./app-header.css";

interface AppHeaderProps {
  summary: Summary | null;
  mode: ViewMode;
  onModeChange: (mode: ViewMode) => void;
  scenarios: { name: string; description: string }[];
  activeScenario: string | null;
  onLoadScenario: (name: string) => void;
}

const MODES: { id: ViewMode; label: string; hint: string; scenarioOnly?: boolean }[] = [
  { id: "nullsignal", label: "NullSignal", hint: "Risk and sufficiency as separate channels" },
  { id: "baseline", label: "Baseline", hint: "A conventional threshold dashboard" },
  { id: "disagreement", label: "Disagreement", hint: "Where the two engines differ" },
  // Ground truth exists only inside a scenario, because only there does anyone
  // know it. Offering it on live data would be a lie about what we can see.
  { id: "truth", label: "Ground truth", hint: "What was actually happening",
    scenarioOnly: true },
];

export function AppHeader({
  summary, mode, onModeChange, scenarios, activeScenario, onLoadScenario,
}: AppHeaderProps) {
  const overclaimed = summary?.reassured_by_baseline_only ?? 0;
  const modes = MODES.filter((m) => !m.scenarioOnly || activeScenario);

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

      {scenarios.length > 0 && (
        <label className="scenario-picker">
          <span className="label">Scenario</span>
          <select
            value={activeScenario ?? ""}
            onChange={(event) => onLoadScenario(event.target.value)}
          >
            <option value="">Live data</option>
            {scenarios.map((s) => (
              <option key={s.name} value={s.name}>{s.name}</option>
            ))}
          </select>
        </label>
      )}

      <nav className="mode-switch" aria-label="Map view">
        {modes.map(({ id, label, hint }) => (
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
