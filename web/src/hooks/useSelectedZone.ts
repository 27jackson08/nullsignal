import { useCallback, useEffect, useState } from "react";

const PARAM = "zone";

/** Selected tract, persisted in the URL.
 *
 *  A verdict about a specific neighbourhood is the thing an operator would
 *  want to send to a colleague, so it belongs in the address bar rather than
 *  in component state alone. Back and forward work as expected. */
export function useSelectedZone(): [string | null, (geoid: string | null) => void] {
  const [geoid, setGeoid] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get(PARAM),
  );

  useEffect(() => {
    const onPopState = () => {
      setGeoid(new URLSearchParams(window.location.search).get(PARAM));
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const select = useCallback((next: string | null) => {
    setGeoid(next);
    const params = new URLSearchParams(window.location.search);
    if (next) params.set(PARAM, next);
    else params.delete(PARAM);

    const query = params.toString();
    // replaceState, not pushState: clicking across a map would otherwise bury
    // the back button under one entry per tract.
    window.history.replaceState(
      null, "", `${window.location.pathname}${query ? `?${query}` : ""}`,
    );
  }, []);

  return [geoid, select];
}
