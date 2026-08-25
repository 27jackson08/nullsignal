import { useEffect, useState } from "react";

import { AppHeader } from "./components/header/AppHeader";
import { StateLegend } from "./components/legend/StateLegend";
import { EvidencePanel } from "./components/panel/EvidencePanel";
import { FeedHealthPanel } from "./components/feeds/FeedHealthPanel";
import { ZoneMap, type ViewMode } from "./components/map/ZoneMap";
import { useSelectedZone } from "./hooks/useSelectedZone";
import { useScenario } from "./hooks/useScenario";
import { useZones } from "./hooks/useZones";
import { Timeline } from "./components/timeline/Timeline";
import { fetchScenarios, type ScenarioSummary } from "./lib/api";
import "./styles/global.css";

export default function App() {
  const { zones, summary, error, isLoading } = useZones();
  const [mode, setMode] = useState<ViewMode>("nullsignal");
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const scenario = useScenario();

  useEffect(() => {
    fetchScenarios().then(setScenarios).catch(() => setScenarios([]));
  }, []);

  // Ground truth is only knowable inside a scenario, so leaving that view
  // selected after returning to live data would show a lie.
  useEffect(() => {
    if (!scenario.name && mode === "truth") setMode("nullsignal");
  }, [scenario.name, mode]);
  const [selectedGeoid, setSelectedGeoid] = useSelectedZone();

  return (
    <div className={scenario.playback ? "app-shell has-timeline" : "app-shell"}>
      <AppHeader
        summary={summary}
        mode={mode}
        onModeChange={setMode}
        scenarios={scenarios}
        activeScenario={scenario.name}
        onLoadScenario={(name) => (name ? scenario.load(name) : scenario.exit())}
      />
      <div className="app-body">
        <main className="map-region">
          {error && (
            <div className="boot-message boot-error">
              <p className="label">Engine unreachable</p>
              <p>{error}</p>
              <pre>uv run nullsignal snapshot{"\n"}uv run nullsignal build{"\n"}uv run nullsignal serve</pre>
            </div>
          )}
          {isLoading && !error && (
            <div className="boot-message"><p className="label">Loading tracts…</p></div>
          )}
          {zones && (
            <>
              <ZoneMap zones={zones} mode={mode} selectedGeoid={selectedGeoid}
                       onSelect={setSelectedGeoid} view={scenario.view} />
              <StateLegend summary={summary} mode={mode} zones={zones} view={scenario.view} />
              {/* Hidden during playback: this panel reports live polling, and
                  showing "all live" while the timeline says the feed froze an
                  hour ago is the precise contradiction this project exists to
                  catch. The scenario's own faults are shown on the timeline. */}
              {!scenario.playback && <FeedHealthPanel feeds={summary?.feeds ?? []} />}
            </>
          )}
        </main>
        <EvidencePanel geoid={selectedGeoid} onSelect={setSelectedGeoid} />
      </div>
      {scenario.playback && (
        <Timeline
          playback={scenario.playback}
          view={scenario.view}
          tick={scenario.tick}
          isPlaying={scenario.isPlaying}
          onSeek={scenario.seek}
          onTogglePlay={scenario.togglePlay}
          onExit={scenario.exit}
        />
      )}
    </div>
  );
}
