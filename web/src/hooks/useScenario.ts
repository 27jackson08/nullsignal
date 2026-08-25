import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { TickView, fetchPlayback, type Playback } from "../lib/playback";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const PLAY_INTERVAL_MS = 900;

export function useScenario() {
  const [name, setName] = useState<string | null>(null);
  const [playback, setPlayback] = useState<Playback | null>(null);
  const [tick, setTick] = useState(0);
  const [isPlaying, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!name) { setPlayback(null); setTick(0); return; }
    let cancelled = false;
    setError(null);
    setPlayback(null);

    fetchPlayback(API_BASE, name)
      .then((loaded) => { if (!cancelled) { setPlayback(loaded); setTick(0); } })
      .catch((err: Error) => { if (!cancelled) setError(err.message); });

    return () => { cancelled = true; };
  }, [name]);

  // Playback stops at the end rather than looping: the last frame is the
  // reveal, and looping past it undercuts the point being made.
  useEffect(() => {
    if (!isPlaying || !playback) return;
    timer.current = window.setInterval(() => {
      setTick((current) => {
        if (current >= playback.ticks.length - 1) { setPlaying(false); return current; }
        return current + 1;
      });
    }, PLAY_INTERVAL_MS);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [isPlaying, playback]);

  const view = useMemo(
    () => (playback && playback.ticks[tick])
      ? new TickView(playback, playback.ticks[tick])
      : null,
    [playback, tick],
  );

  const seek = useCallback((next: number) => {
    setPlaying(false);
    setTick(next);
  }, []);

  const exit = useCallback(() => {
    setPlaying(false);
    setName(null);
  }, []);

  return {
    name, playback, view, tick, isPlaying, error,
    load: setName, seek, exit,
    togglePlay: () => setPlaying((on) => !on),
  };
}
