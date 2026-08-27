import type { SourceLink } from "../../lib/api";

/**
 * Where a reader goes to check the claim themselves.
 *
 * A finding nobody can verify is an assertion, and a project about evidence
 * sufficiency has no standing to make those. These are the datasets, not a
 * citation of them: the links open the rows.
 */
export function SourceList({ sources }: { sources: SourceLink[] }) {
  if (!sources.length) return null;
  return (
    <ul className="source-list">
      {sources.map((s) => (
        <li key={s.url}>
          <a href={s.url} target="_blank" rel="noopener noreferrer">{s.label}</a>
          <span className="note">{s.note}</span>
        </li>
      ))}
    </ul>
  );
}
