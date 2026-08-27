import { useEffect, useState } from "react";

import { AppHeader } from "./components/header/AppHeader";
import { StateLegend } from "./components/legend/StateLegend";
import { EvidencePanel } from "./components/panel/EvidencePanel";
import { FeedHealthPanel } from "./components/feeds/FeedHealthPanel";
import { ZoneMap, type ViewMode } from "./components/map/ZoneMap";
import { CompareView } from "./components/compare/CompareView";
import { Scoreboard } from "./components/scoreboard/Scoreboard";
import { Welcome, hasBeenWelcomed } from "./components/welcome/Welcome";
import { CoolingFinding } from "./components/findings/CoolingFinding";
import { ShiftBriefing } from "./components/briefing/ShiftBriefing";
import { useSurface } from "./hooks/useSurface";
import { useSelectedZone } from "./hooks/useSelectedZone";
import { useScenario } from "./hooks/useScenario";
import { useZones } from "./hooks/useZones";
import { Timeline } from "./components/timeline/Timeline";
import { fetchScenarios, type ScenarioSummary } from "./lib/api";
import "./styles/global.css";

export default function App() {
  const [mode, setMode] = useState<ViewMode>("nullsignal");
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const scenario = useScenario();
  const [surface, setSurface] = useSurface();
  const { zones, summary, error, isLoading } = useZones(surface === "console");

  useEffect(() => {
    fetchScenarios().then(setScenarios).catch(() => setScenarios([]));
  }, []);

  // Ground truth is only knowable inside a scenario, so leaving that view
  // selected after returning to live data would show a lie.
  useEffect(() => {
    if (!scenario.name && (mode === "truth" || mode === "result")) setMode("nullsignal");
  }, [scenario.name, mode]);
  const [selectedGeoid, setSelectedGeoid] = useSelectedZone();

  // Shown once per browser. A judge opening a link has no idea that hatching
  // is the point, and the map alone does not say so.
  const [showWelcome, setShowWelcome] = useState(() => !hasBeenWelcomed());

  return (
    <div className={scenario.playback && surface === "console"
      ? "app-shell has-timeline" : "app-shell"}>
      <AppHeader
        summary={summary}
        mode={mode}
        onModeChange={setMode}
        scenarios={scenarios}
        activeScenario={scenario.name}
        onLoadScenario={(name) => (name ? scenario.load(name) : scenario.exit())}
        surface={surface}
        onSurfaceChange={setSurface}
      />
      {surface !== "console" ? (
        <div className="app-body is-full">
          {/* tabIndex on the scrolling region: it is the only way a
              keyboard-only reader can scroll a long record, and it carries the
              main landmark for the surface. */}
          <main className="surface-scroll" tabIndex={0}>
            {surface === "briefing"
              ? <ShiftBriefing onOpenAudit={() => setSurface("cooling")} />
              : <CoolingFinding />}
          </main>
        </div>
      ) : (
      <div className={mode === "result" ? "app-body is-full" : "app-body"}>
        <main className="map-region">
          {/* Only over the map. The briefing states what it is in its own
              headline; a modal explaining it would be noise. */}
          {showWelcome && surface === "console" && !isLoading && !error && (
            <Welcome
              unknownCount={summary?.reassured_by_baseline_only ?? null}
              zoneCount={summary?.zone_count ?? null}
              onDismiss={() => setShowWelcome(false)}
              onLoadScenario={(name) => scenario.load(name)}
            />
          )}
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
          {mode === "result" && scenario.playback && (
            <Scoreboard playback={scenario.playback} />
          )}
          {zones && mode === "compare" && (
            <CompareView zones={zones} summary={summary} view={scenario.view}
                         selectedGeoid={selectedGeoid} onSelect={setSelectedGeoid} />
          )}
          {zones && mode !== "compare" && mode !== "result" && (
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
        {/* The result view is a conclusion, not a workspace: the tract panel
            beside it competes for attention with the one number the run
            produced. */}
        {mode !== "result" && (
          <EvidencePanel geoid={selectedGeoid} onSelect={setSelectedGeoid} />
        )}
      </div>
      )}
      {surface === "console" && scenario.playback && (
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
