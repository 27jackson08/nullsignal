import { useState } from "react";
import { zoomIdentity, type ZoomTransform } from "d3-zoom";

import { ZoneMap } from "../map/ZoneMap";
import type { ZoneCollection, Summary } from "../../lib/api";
import type { TickView } from "../../lib/playback";
import "./compare.css";

interface CompareViewProps {
  zones: ZoneCollection;
  summary: Summary | null;
  view: TickView | null;
  selectedGeoid: string | null;
  onSelect: (geoid: string | null) => void;
}

/** The two engines on the same evidence, at the same moment, side by side.
 *
 *  Toggling between them asks a viewer to hold two frames in their head and
 *  spot the difference. Showing both at once removes that work entirely: one
 *  map goes hatched and the other does not move. */
export function CompareView({
  zones, summary, view, selectedGeoid, onSelect,
}: CompareViewProps) {
  // One viewport shared by both panes.
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);

  const counts = (side: "nullsignal" | "baseline") => {
    if (view) {
      let unknown = 0;
      let safe = 0;
      for (const feature of zones.features) {
        const state = side === "baseline"
          ? view.baselineStateFor(feature.properties.geoid)
          : view.stateFor(feature.properties.geoid);
        if (state === "UNKNOWN") unknown += 1;
        if (state === "CONFIRMED_LOW") safe += 1;
      }
      return { unknown, safe };
    }
    const live = summary?.states[side] ?? {};
    return { unknown: live.UNKNOWN ?? 0, safe: live.CONFIRMED_LOW ?? 0 };
  };

  const theirs = counts("baseline");
  const ours = counts("nullsignal");

  return (
    <div className="compare">
      <section className="pane">
        <header>
          <p className="label">Conventional dashboard</p>
          <p className="pane-read">
            <span className="numeric">{theirs.safe.toLocaleString()}</span> called safe
            <span className="sep">&middot;</span>
            <span className="numeric">{theirs.unknown.toLocaleString()}</span> unknown
          </p>
        </header>
        <ZoneMap
          zones={zones} mode="baseline" view={view}
          selectedGeoid={selectedGeoid} onSelect={onSelect}
          transform={transform} onTransformChange={setTransform}
          quiet
        />
      </section>

      <section className="pane is-ours">
        <header>
          <p className="label">NullSignal</p>
          <p className="pane-read">
            <span className="numeric">{ours.safe.toLocaleString()}</span> called safe
            <span className="sep">&middot;</span>
            <span className="numeric emphasis">{ours.unknown.toLocaleString()}</span> unknown
          </p>
        </header>
        <ZoneMap
          zones={zones} mode="nullsignal" view={view}
          selectedGeoid={selectedGeoid} onSelect={onSelect}
          transform={transform} onTransformChange={setTransform}
        />
      </section>
    </div>
  );
}
