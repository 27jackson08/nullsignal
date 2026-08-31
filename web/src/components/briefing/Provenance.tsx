import { useEffect, useState } from "react";

import { fetchSummary, type Summary } from "../../lib/api";
import "./provenance.css";

const BYTES = (n: number) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB`
  : n >= 1e3 ? `${Math.round(n / 1e3)} kB`
  : `${n} B`;

function when(iso: string | null): string {
  if (!iso) return "time not recorded";
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? "time not recorded"
    : at.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/**
 * What this order was computed from.
 *
 * The manifest has always been written and never shown. A project whose
 * argument is that unattributed data is the problem should be able to answer
 * "where did this come from" without anyone reading the repository, so the
 * hashes are here: every figure on this page derives from these bytes.
 */
export function Provenance() {
  const [summary, setSummary] = useState<Summary | null>(null);

  useEffect(() => {
    fetchSummary().then(setSummary).catch(() => setSummary(null));
  }, []);

  const sources = summary?.snapshot?.sources;
  if (!sources?.length) return null;

  return (
    <div className="provenance">
      <div className="record-table-wrap">
        <table className="record-table provenance-table">
          <caption className="sr-only">
            Sources this briefing was computed from
          </caption>
          <thead>
            <tr>
              <th scope="col">Source</th>
              <th scope="col">Fetched</th>
              <th scope="col">Content hash</th>
              <th scope="col" className="num">Size</th>
            </tr>
          </thead>
          <tbody>
            {[...sources]
              .sort((a, b) => a.source_id.localeCompare(b.source_id))
              .map((s) => (
                <tr key={s.source_id}>
                  <td className="place">{s.source_id}</td>
                  <td className={s.fetched_at ? "quiet" : "quiet unrecorded"}>
                    {when(s.fetched_at)}
                  </td>
                  <td className="hash fig">{s.content_hash}</td>
                  <td className="num fig">{BYTES(s.bytes)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {sources.some((s) => !s.fetched_at) && (
        <p className="provenance-note">
          Four entries carry no fetch time. A partial snapshot once overwrote
          the manifest instead of merging into it, and those timestamps went
          with it. The hashes are recomputed from the committed files and
          verified by the suite; the times are not recoverable and are not
          invented.
        </p>
      )}
    </div>
  );
}
