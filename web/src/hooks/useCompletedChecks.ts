import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "nullsignal.checks";

/** What a crew reported back. */
export type Outcome = "clear" | "problem";

export type CompletedChecks = Record<string, Outcome>;

function read(): CompletedChecks {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as CompletedChecks) : {};
  } catch {
    // Blocked storage, or somebody else's JSON under our key. Losing a shift's
    // ticks is a smaller failure than refusing to render the briefing.
    return {};
  }
}

/**
 * Checks carried out this shift, keyed by tract.
 *
 * Held here rather than on a server because there is no server: the point is
 * that recording a result resolves the doubt it was blocking, and the engine
 * has already computed what each tract becomes. This only remembers which
 * answer came back.
 */
export function useCompletedChecks() {
  const [completed, setCompleted] = useState<CompletedChecks>(read);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(completed));
    } catch {
      /* nothing to do: the tick simply does not survive a reload */
    }
  }, [completed]);

  const record = useCallback((geoid: string, outcome: Outcome) => {
    setCompleted((previous) => ({ ...previous, [geoid]: outcome }));
  }, []);

  const undo = useCallback((geoid: string) => {
    setCompleted((previous) => {
      const next = { ...previous };
      delete next[geoid];
      return next;
    });
  }, []);

  const clear = useCallback(() => setCompleted({}), []);

  return { completed, record, undo, clear };
}
