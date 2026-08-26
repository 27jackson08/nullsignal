import { useCallback, useEffect, useState } from "react";

const PARAM = "surface";

/** Which top-level surface is open.
 *
 *  In the URL because a finding is the thing worth sending to someone: a
 *  colleague opening the link should land on the claim, not on a map they then
 *  have to navigate.
 *
 *  The briefing is the default. A map of New York is the most commoditised
 *  artefact in civic software and says nothing on its own about what this
 *  produces; the work order says it in a headline. The map is one click away
 *  and is where the argument gets checked, not where it gets made. */
export type Surface = "briefing" | "console" | "cooling";

const SURFACES: readonly Surface[] = ["briefing", "console", "cooling"];

const DEFAULT_SURFACE: Surface = "briefing";

function read(): Surface {
  const value = new URLSearchParams(window.location.search).get(PARAM);
  return SURFACES.includes(value as Surface) ? (value as Surface) : DEFAULT_SURFACE;
}

export function useSurface(): [Surface, (next: Surface) => void] {
  const [surface, setSurface] = useState<Surface>(read);

  useEffect(() => {
    const onPopState = () => setSurface(read());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const go = useCallback((next: Surface) => {
    setSurface(next);
    const params = new URLSearchParams(window.location.search);
    if (next === DEFAULT_SURFACE) params.delete(PARAM);
    else params.set(PARAM, next);

    const query = params.toString();
    // pushState here, unlike tract selection: moving between the console and a
    // finding is a navigation, and back should return you to where you were.
    window.history.pushState(
      null, "", `${window.location.pathname}${query ? `?${query}` : ""}`,
    );
  }, []);

  return [surface, go];
}
