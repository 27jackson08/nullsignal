import { useEffect, useState } from "react";

import { fetchQueue, type QueueEntry } from "../../lib/api";
import "./verification-queue.css";

interface VerificationQueueProps {
  onSelect: (geoid: string) => void;
  limit?: number;
}

/** What to look at next, and why.
 *
 *  Ordered by unresolved harm -- believed harm weighted by remaining doubt --
 *  rather than by risk. A tract we are confident about needs no attention
 *  however bad it is; a fragile tract we cannot see does. */
export function VerificationQueue({ onSelect, limit = 8 }: VerificationQueueProps) {
  const [entries, setEntries] = useState<QueueEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchQueue(limit)
      .then((rows) => { if (!cancelled) setEntries(rows); })
      .catch((err: Error) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [limit]);

  if (error) return <p className="queue-error">{error}</p>;
  if (!entries) return null;

  return (
    <section className="verification-queue">
      <p className="label">Where to look first</p>
      <p className="queue-note">
        Ranked by expected residents at stake &mdash; harm we believe in,
        weighted by the doubt still on it, times the people it falls on. Not by
        risk: a tract we understand needs no attention however bad it is.
      </p>
      <p className="queue-note">
        Most of these were called, and called narrowly. A tract marked{" "}
        <strong>unknown</strong> could not be called at all, and its check is
        the one that would settle it &mdash; those are the ones on{" "}
        tonight&rsquo;s briefing.
      </p>
      <ol>
        {entries.map((entry) => (
          <li key={entry.geoid}>
            <button type="button" onClick={() => onSelect(entry.geoid)}>
              <span className="q-name">
                {entry.name}
                {entry.state === "UNKNOWN" && (
                  <span className="q-state">unknown</span>
                )}
              </span>
              <span className="q-meta numeric">
                {Math.round(entry.residents_at_stake).toLocaleString()} at stake
                &middot; {entry.population.toLocaleString()} residents
                &middot; {entry.borough}
              </span>
              {entry.next_check_kind === "unresolvable" ? (
                /* Naming a check here would read as "do this and you will
                   know". Nothing in the catalogue would settle these. */
                <span className="q-check is-stuck">No check would settle this</span>
              ) : entry.next_check && (
                <span className={entry.next_check_kind === "resolves"
                  ? "q-check is-resolving" : "q-check"}>
                  {entry.next_check}
                  <span className="q-time numeric"> {entry.next_check_minutes}m</span>
                </span>
              )}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
