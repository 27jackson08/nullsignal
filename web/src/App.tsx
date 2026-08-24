import { useState } from "react";

import { AppHeader } from "./components/header/AppHeader";
import { StateLegend } from "./components/legend/StateLegend";
import { EvidencePanel } from "./components/panel/EvidencePanel";
import { ZoneMap, type ViewMode } from "./components/map/ZoneMap";
import { useZones } from "./hooks/useZones";
import "./styles/global.css";

export default function App() {
  const { zones, summary, error, isLoading } = useZones();
  const [mode, setMode] = useState<ViewMode>("nullsignal");
  const [selectedGeoid, setSelectedGeoid] = useState<string | null>(null);

  return (
    <div className="app-shell">
      <AppHeader summary={summary} mode={mode} onModeChange={setMode} />
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
                       onSelect={setSelectedGeoid} />
              <StateLegend summary={summary} mode={mode} />
            </>
          )}
        </main>
        <EvidencePanel geoid={selectedGeoid} />
      </div>
    </div>
  );
}
