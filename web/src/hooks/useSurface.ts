import { useCallback, useEffect, useState } from "react";

const PARAM = "surface";

/** Which top-level surface is open: the live console, or a finding.
 *
 *  In the URL because a finding is the thing worth sending to someone. A
 *  colleague opening the link should land on the claim, not on a map they then
 *  have to navigate. */
export type Surface = "briefing" | "console" | "cooling";

const SURFACES: readonly Surface[] = ["briefing", "console", "cooling"];

function read(): Surface {
  const value = new URLSearchParams(window.location.search).get(PARAM);
  return SURFACES.includes(value as Surface) ? (value as Surface) : "console";
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
    if (next === "console") params.delete(PARAM);
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
