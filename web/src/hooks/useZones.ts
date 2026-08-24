import { useEffect, useState } from "react";

import { fetchSummary, fetchZones, type Summary, type ZoneCollection } from "../lib/api";

interface ZonesState {
  zones: ZoneCollection | null;
  summary: Summary | null;
  error: string | null;
  isLoading: boolean;
}

export function useZones(): ZonesState {
  const [state, setState] = useState<ZonesState>({
    zones: null, summary: null, error: null, isLoading: true,
  });

  useEffect(() => {
    let cancelled = false;

    Promise.all([fetchZones(), fetchSummary()])
      .then(([zones, summary]) => {
        if (cancelled) return;
        setState({ zones, summary, error: null, isLoading: false });
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setState({ zones: null, summary: null, error: error.message, isLoading: false });
      });

    return () => { cancelled = true; };
  }, []);

  return state;
}
