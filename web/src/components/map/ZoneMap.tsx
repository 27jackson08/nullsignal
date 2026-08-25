import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { geoMercator, geoPath, type GeoProjection } from "d3-geo";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type D3ZoomEvent, type ZoomTransform } from "d3-zoom";

import { createHatchPattern } from "../../lib/hatch";
import { colourToIndex, indexToColour } from "../../lib/pickIndex";
import { STATE_META } from "../../lib/states";
import type { ZoneCollection, ZoneProperties } from "../../lib/api";
import type { TickView, Truth } from "../../lib/playback";
import "./zone-map.css";

export type ViewMode = "nullsignal" | "baseline" | "disagreement" | "truth";

/** Ground truth is coloured on its own scale, not the decision palette.
 *  Truth is what *is*; the four decision states are what a system was willing
 *  to say. Sharing a palette between them would blur exactly the distinction
 *  the scenario exists to draw. */
const TRUTH_FILL: Record<Truth, string> = {
  normal: "#1D2530",
  heat: "#8A6A1F",
  heat_stranded: "#B33A31",
  local_fault: "#2F4A63",
};

interface ZoneMapProps {
  zones: ZoneCollection;
  mode: ViewMode;
  selectedGeoid: string | null;
  onSelect: (geoid: string | null) => void;
  /** When a scenario is playing, states come from the tick rather than live. */
  view?: TickView | null;
}

const ZOOM_RANGE: [number, number] = [1, 40];
const AGREEMENT_FILL = "#1D2530";
const GROUND = "#0B0E13";
const BORDER = "#0B0E13";
const PADDING = 8;

/** Hue encodes the risk estimate and never encodes sufficiency -- that is the
 *  hatch pass's job. Merging the channels would rebuild the single
 *  green-to-red ramp this product exists to replace. */
function fillFor(
  properties: ZoneProperties,
  mode: ViewMode,
  view?: TickView | null,
): string {
  if (view) {
    const ours = view.stateFor(properties.geoid);
    const theirs = view.baselineStateFor(properties.geoid);
    if (mode === "truth") {
      const truth = view.truthFor(properties.geoid);
      return truth ? TRUTH_FILL[truth] : AGREEMENT_FILL;
    }
    if (mode === "disagreement") {
      if (theirs === "CONFIRMED_LOW" && ours !== "CONFIRMED_LOW") {
        return STATE_META.CONFIRMED_HIGH.color;
      }
      return ours !== theirs ? STATE_META.SUSPECTED.color : AGREEMENT_FILL;
    }
    const state = mode === "baseline" ? theirs : ours;
    return state ? STATE_META[state].color : AGREEMENT_FILL;
  }

  if (mode === "truth") return AGREEMENT_FILL;
  if (mode === "disagreement") {
    const baselineReassures = properties.baseline_state === "CONFIRMED_LOW";
    if (baselineReassures && properties.state !== "CONFIRMED_LOW") {
      return STATE_META.CONFIRMED_HIGH.color;
    }
    return properties.disagrees ? STATE_META.SUSPECTED.color : AGREEMENT_FILL;
  }
  const state = mode === "baseline" ? properties.baseline_state : properties.state;
  return STATE_META[state]?.color ?? AGREEMENT_FILL;
}

function isHatched(
  properties: ZoneProperties,
  mode: ViewMode,
  view?: TickView | null,
): boolean {
  if (mode === "disagreement" || mode === "truth") return false;
  if (view) {
    const state = mode === "baseline"
      ? view.baselineStateFor(properties.geoid)
      : view.stateFor(properties.geoid);
    return state ? STATE_META[state].hatched : false;
  }
  const state = mode === "baseline" ? properties.baseline_state : properties.state;
  return STATE_META[state]?.hatched ?? false;
}

export function ZoneMap({ zones, mode, selectedGeoid, onSelect, view }: ZoneMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const pickCanvasRef = useRef<HTMLCanvasElement | null>(null);

  const [size, setSize] = useState({ width: 0, height: 0 });
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const applySize = (width: number, height: number) => {
      // A zero-size report (hidden tab, display:none ancestor) is not a real
      // layout; adopting it would blank the map and then never recover,
      // because no further resize is guaranteed to arrive.
      if (width < 1 || height < 1) return;
      setSize((current) =>
        current.width === Math.round(width) && current.height === Math.round(height)
          ? current
          : { width: Math.round(width), height: Math.round(height) },
      );
    };

    const rect = element.getBoundingClientRect();
    applySize(rect.width, rect.height);

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      applySize(width, height);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const projection = useMemo<GeoProjection | null>(() => {
    if (!size.width || !size.height || !zones.features.length) return null;
    return geoMercator().fitExtent(
      [[PADDING, PADDING], [size.width - PADDING, size.height - PADDING]],
      zones,
    );
  }, [zones, size.width, size.height]);

  // Centroids in screen space, for keyboard navigation and the focus ring.
  // Computed with the projection rather than per keypress: finding the nearest
  // tract in a direction is a scan over all of them, and reprojecting on every
  // arrow press would make the map feel broken to exactly the users who depend
  // on it most.
  const centroids = useMemo(() => {
    if (!projection) return [];
    const toPath = geoPath(projection);
    return zones.features.map((feature) => {
      const [x, y] = toPath.centroid(feature);
      return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
    });
  }, [zones, projection]);

  const selectedIndex = useMemo(
    () => (selectedGeoid
      ? zones.features.findIndex((f) => f.properties.geoid === selectedGeoid)
      : -1),
    [zones, selectedGeoid],
  );

  // --- main render ----------------------------------------------------------
  // Canvas rather than SVG: 2,300 tract polygons as DOM nodes made every mode
  // switch re-render the whole tree and froze the main thread for tens of
  // seconds. Drawing is immediate-mode here, so a full repaint is milliseconds
  // and touches no DOM.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !projection || !size.width) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = size.width * dpr;
    canvas.height = size.height * dpr;

    // Drawn synchronously rather than inside requestAnimationFrame. A full
    // repaint of every tract is a few milliseconds, so deferring buys nothing,
    // and rAF does not fire at all while the tab is backgrounded -- which left
    // the canvas blank until the tab was focused.
    {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = GROUND;
      ctx.fillRect(0, 0, size.width, size.height);

      ctx.save();
      ctx.translate(transform.x, transform.y);
      ctx.scale(transform.k, transform.k);

      const toPath = geoPath(projection, ctx);

      // Pass 1: hue.
      ctx.lineWidth = 0.4 / transform.k;
      ctx.strokeStyle = BORDER;
      zones.features.forEach((feature) => {
        ctx.beginPath();
        toPath(feature);
        ctx.fillStyle = fillFor(feature.properties, mode, view);
        ctx.fill();
        ctx.stroke();
      });

      // Pass 2: texture, clipped to low-sufficiency tracts and drawn in screen
      // space so the hatch stays a constant size as you zoom.
      const hatched = zones.features.filter((f) => isHatched(f.properties, mode, view));
      if (hatched.length) {
        ctx.save();
        ctx.beginPath();
        hatched.forEach((feature) => toPath(feature));
        ctx.clip();
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const pattern = createHatchPattern(ctx);
        if (pattern) {
          ctx.fillStyle = pattern;
          ctx.fillRect(0, 0, size.width, size.height);
        }
        ctx.restore();
      }

      // Pass 3: hover and selection outlines.
      const outline = (index: number, colour: string, width: number) => {
        const feature = zones.features[index];
        if (!feature) return;
        ctx.beginPath();
        toPath(feature);
        ctx.strokeStyle = colour;
        ctx.lineWidth = width / transform.k;
        ctx.stroke();
      };
      if (hoveredIndex !== null && hoveredIndex !== selectedIndex) {
        outline(hoveredIndex, "#97A3B4", 1.4);
      }
      // Keyboard focus is drawn thicker than hover and in the accent, so it is
      // distinguishable without relying on a pointer being present.
      if (focusedIndex !== null && focusedIndex !== selectedIndex) {
        outline(focusedIndex, "#7FB2E0", 2.4);
      }
      if (selectedIndex >= 0) outline(selectedIndex, "#E6EBF2", 2);

      ctx.restore();
    }
  }, [zones, projection, mode, transform, size, hoveredIndex, focusedIndex,
      selectedIndex, view]);

  // --- hit-test buffer ------------------------------------------------------
  // Redrawn only when geometry or viewport changes, never on hover.
  useEffect(() => {
    if (!projection || !size.width) return;

    const canvas = pickCanvasRef.current ?? document.createElement("canvas");
    pickCanvasRef.current = canvas;
    canvas.width = size.width;
    canvas.height = size.height;

    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, size.width, size.height);
    ctx.translate(transform.x, transform.y);
    ctx.scale(transform.k, transform.k);

    const toPath = geoPath(projection, ctx);
    zones.features.forEach((feature, index) => {
      ctx.beginPath();
      toPath(feature);
      ctx.fillStyle = indexToColour(index);
      ctx.fill();
    });
  }, [zones, projection, transform, size]);

  const pick = useCallback((event: React.MouseEvent<HTMLCanvasElement>): number | null => {
    const canvas = pickCanvasRef.current;
    const target = canvasRef.current;
    if (!canvas || !target) return null;

    const rect = target.getBoundingClientRect();
    const x = Math.round(event.clientX - rect.left);
    const y = Math.round(event.clientY - rect.top);
    if (x < 0 || y < 0 || x >= canvas.width || y >= canvas.height) return null;

    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return null;

    const [r, g, b, a] = ctx.getImageData(x, y, 1, 1).data;
    const index = colourToIndex(r, g, b, a);
    return index !== null && index >= 0 && index < zones.features.length ? index : null;
  }, [zones]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !size.width) return;

    const behaviour = zoom<HTMLCanvasElement, unknown>()
      .scaleExtent(ZOOM_RANGE)
      .on("zoom", (event: D3ZoomEvent<HTMLCanvasElement, unknown>) =>
        setTransform(event.transform));

    const selection = select(canvas);
    selection.call(behaviour);
    return () => { selection.on(".zoom", null); };
  }, [size.width, size.height]);

  /** Nearest tract in the direction pressed.
   *
   *  Spatial rather than list-order: arrowing right across a map should move
   *  right across the map. A tab order down an alphabetical list would be
   *  technically operable and practically useless for understanding geography,
   *  which is the entire point of the view. */
  const step = useCallback((dx: number, dy: number) => {
    const from = focusedIndex ?? selectedIndex;
    const origin = from >= 0 ? centroids[from] : null;

    let bestIndex = -1;
    let bestCost = Number.POSITIVE_INFINITY;

    centroids.forEach((point, index) => {
      if (!point || index === from) return;

      let cost: number;
      if (!origin) {
        cost = point.x + point.y;   // no anchor yet: enter near the top-left
      } else {
        const ax = point.x - origin.x;
        const ay = point.y - origin.y;
        const along = ax * dx + ay * dy;
        if (along <= 0) return;                     // wrong side
        const across = Math.abs(ax * dy - ay * dx);
        if (across > along * 2.5) return;           // too far off-axis
        cost = along + across * 2;                  // prefer straight ahead
      }

      if (cost < bestCost) {
        bestCost = cost;
        bestIndex = index;
      }
    });

    if (bestIndex >= 0) setFocusedIndex(bestIndex);
  }, [centroids, focusedIndex, selectedIndex]);

  const onKeyDown = useCallback((event: React.KeyboardEvent<HTMLCanvasElement>) => {
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
    };
    const move = moves[event.key];
    if (move) {
      event.preventDefault();
      step(move[0], move[1]);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (focusedIndex !== null) onSelect(zones.features[focusedIndex].properties.geoid);
      return;
    }
    if (event.key === "Escape") {
      setFocusedIndex(null);
      onSelect(null);
    }
  }, [step, focusedIndex, zones, onSelect]);

  const hovered = hoveredIndex !== null ? zones.features[hoveredIndex]?.properties : undefined;
  const focused = focusedIndex !== null ? zones.features[focusedIndex]?.properties : undefined;

  return (
    <div className="zone-map" ref={containerRef}>
      <canvas
        ref={canvasRef}
        className="zone-canvas"
        style={{ width: size.width, height: size.height, cursor: hovered ? "pointer" : "grab" }}
        role="application"
        tabIndex={0}
        aria-label={"New York City census tracts by risk and evidence sufficiency. "
          + "Use the arrow keys to move between tracts, Enter to open one, "
          + "Escape to clear."}
        aria-describedby="map-live-region"
        onKeyDown={onKeyDown}
        onBlur={() => setFocusedIndex(null)}
        onMouseMove={(event) => setHoveredIndex(pick(event))}
        onMouseLeave={() => setHoveredIndex(null)}
        onClick={(event) => {
          const index = pick(event);
          onSelect(index === null ? null : zones.features[index].properties.geoid);
        }}
      />

      {hovered && (
        <p className="zone-hover" aria-hidden="true">
          <span className="hover-name">{hovered.name}</span>
          <span className="hover-state">
            {(() => {
              const state = view ? view.stateFor(hovered.geoid) : hovered.state;
              return state ? STATE_META[state].label : hovered.state;
            })()}
          </span>
        </p>
      )}

      {/* Announced to assistive technology as focus moves. Visually hidden
          rather than absent: the canvas itself conveys nothing to a screen
          reader, so this is the only channel that carries the verdict. */}
      <p id="map-live-region" className="visually-hidden" role="status" aria-live="polite">
        {focused
          ? `${focused.name}, ${focused.borough}. `
            + `${STATE_META[view?.stateFor(focused.geoid) ?? focused.state]?.label ?? ""}. `
            + `${focused.population.toLocaleString()} residents.`
          : ""}
      </p>

      <p className="zoom-hint label" aria-hidden="true">scroll to zoom &middot; drag to pan</p>
    </div>
  );
}
