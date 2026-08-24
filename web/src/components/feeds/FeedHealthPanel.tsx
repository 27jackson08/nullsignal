import { useState } from "react";

import type { FeedHealth } from "../../lib/api";
import "./feed-health.css";

interface FeedHealthPanelProps {
  feeds: FeedHealth[];
}

const SOURCE_LABELS: Record<string, string> = {
  gtfs_rt: "Transit realtime",
  nws: "Weather",
  "311": "Reports",
};

const DETECTOR_LABELS: Record<string, string> = {
  cadence_violation: "Clock advancing",
  content_flatline: "Payload changing",
  value_flatline: "Reading varying",
};

export function FeedHealthPanel({ feeds }: FeedHealthPanelProps) {
  const [expanded, setExpanded] = useState(false);
  if (!feeds.length) return null;

  const degraded = feeds.filter((feed) => feed.liveness < 1).length;
  const unchecked = feeds.reduce(
    (total, feed) => total + feed.detectors.filter((d) => !d.assessable).length, 0,
  );

  return (
    <aside className={expanded ? "feed-health is-expanded" : "feed-health"}>
      <button type="button" onClick={() => setExpanded((open) => !open)}
              aria-expanded={expanded}>
        <span className="label">Feed health</span>
        <span className={degraded ? "verdict is-degraded" : "verdict"}>
          {degraded ? `${degraded} degraded` : "all live"}
        </span>
      </button>

      {expanded && (
        <div className="feed-detail">
          {feeds.map((feed) => (
            <article key={feed.source_id}>
              <header>
                <span className="feed-name">
                  {SOURCE_LABELS[feed.source_id] ?? feed.source_id}
                </span>
                <span className="feed-polls numeric">{feed.poll_count} polls</span>
              </header>
              <ul>
                {feed.detectors.map((detector) => (
                  <li key={detector.name}
                      className={detector.fired ? "is-fired"
                        : detector.assessable ? "is-ok" : "is-unchecked"}>
                    <span className="dot" aria-hidden="true" />
                    <span className="det-name">
                      {DETECTOR_LABELS[detector.name] ?? detector.name}
                    </span>
                    <span className="det-detail">{detector.detail}</span>
                  </li>
                ))}
              </ul>
            </article>
          ))}
          {unchecked > 0 && (
            <p className="unchecked-note">
              {unchecked} {unchecked === 1 ? "check has" : "checks have"} not run yet
              &mdash; not the same as passing.
            </p>
          )}
        </div>
      )}
    </aside>
  );
}
