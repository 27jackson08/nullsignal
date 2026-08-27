import { useEffect, useState } from "react";

import { fetchSummary, fetchZones, type Summary, type ZoneCollection } from "../lib/api";

interface ZonesState {
  zones: ZoneCollection | null;
  summary: Summary | null;
  error: string | null;
  isLoading: boolean;
}

/**
 * Tract geometry and the citywide summary.
 *
 * `enabled` gates the fetch because the geometry is 1.8 MB and only the map
 * renders it. The briefing is what a link opens on, and pulling the whole city
 * behind a page that never draws it made the landing view cost more than
 * everything else on the site combined. Once fetched it stays; moving back to
 * the briefing does not throw the map away.
 */
export function useZones(enabled = true): ZonesState {
  const [state, setState] = useState<ZonesState>({
    zones: null, summary: null, error: null, isLoading: enabled,
  });

  useEffect(() => {
    if (!enabled || state.zones || state.error) return;
    let cancelled = false;
    setState((previous) => ({ ...previous, isLoading: true }));

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
  }, [enabled, state.zones, state.error]);

  return state;
}
