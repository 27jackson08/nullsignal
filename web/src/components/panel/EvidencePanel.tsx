import { useZoneDetail } from "../../hooks/useZoneDetail";
import { STATE_META, isReassuring } from "../../lib/states";
import { MeterRow } from "./MeterRow";
import "./evidence-panel.css";

interface EvidencePanelProps {
  geoid: string | null;
}

const SOURCE_LABELS: Record<string, string> = {
  nws: "Weather (NWS)",
  cdc_svi: "Vulnerability (CDC SVI)",
  gtfs_rt: "Transit (MTA GTFS-RT)",
  "311": "Reports (311)",
};

const TERM_LABELS: Record<string, string> = {
  entropy: "Hypothesis entropy",
  coverage: "Evidence coverage",
  contradiction: "Source agreement",
  staleness: "Freshness",
};

const UNLOCK_DAY: Record<string, string> = {
  entropy: "Bayesian layer",
  contradiction: "Contradiction graph",
};

export function EvidencePanel({ geoid }: EvidencePanelProps) {
  const { detail, error } = useZoneDetail(geoid);

  if (error) {
    return <section className="evidence-panel"><p className="panel-error">{error}</p></section>;
  }

  if (!detail) {
    return (
      <section className="evidence-panel">
        <div className="panel-empty">
          <p className="label">No tract selected</p>
          <p>
            Pick a tract to see what the engine knows, what it doesn&rsquo;t, and
            why that distinction changed the verdict.
          </p>
        </div>
      </section>
    );
  }

  const meta = STATE_META[detail.state];
  const baselineMeta = STATE_META[detail.baseline_state];
  const overclaimed = isReassuring(detail.baseline_state) && !isReassuring(detail.state);
  const { sufficiency, evidence, vulnerability } = detail;

  return (
    <section className="evidence-panel" aria-live="polite">
      <header className="panel-head">
        <p className="label">{detail.borough} &middot; tract {detail.geoid.slice(-6)}</p>
        <h2>{detail.name}</h2>
        <p className="pop numeric">{detail.population.toLocaleString()} residents</p>
      </header>

      <div className="verdict" style={{ borderColor: meta.color }}>
        <span className={meta.hatched ? "verdict-chip is-hatched" : "verdict-chip"}
              style={{ background: meta.color }}>
          {meta.label}
        </span>
        <p className="verdict-blurb">{meta.blurb}</p>
      </div>

      {overclaimed && (
        <p className="overclaim">
          A conventional dashboard rates this tract{" "}
          <strong>{baselineMeta.label.toLowerCase()}</strong>. That verdict rests on
          evidence this system does not actually have.
        </p>
      )}

      {evidence.missing_critical_sources.length > 0 && (
        <div className="critical-gap">
          <p className="label">Missing decision-critical evidence</p>
          <ul>
            {evidence.missing_critical_sources.map((source) => (
              <li key={source}>{SOURCE_LABELS[source] ?? source}</li>
            ))}
          </ul>
          <p className="critical-note">
            Without these, no safe call is defensible, however healthy the
            remaining feeds look.
          </p>
        </div>
      )}

      <section className="block">
        <p className="label">Sufficiency &middot; {sufficiency.score.toFixed(2)}</p>
        {Object.entries(sufficiency.measured).map(([term, value]) => (
          <MeterRow key={term} label={TERM_LABELS[term] ?? term} value={value} />
        ))}
        {sufficiency.unmeasured.map((term) => (
          <MeterRow
            key={term}
            label={TERM_LABELS[term] ?? term}
            value={null}
            note={`awaiting ${UNLOCK_DAY[term] ?? "implementation"}`}
          />
        ))}
        {sufficiency.ceiling < 1 && (
          <p className="ceiling-note numeric">
            Capped at {sufficiency.ceiling.toFixed(2)} by a missing critical source.
          </p>
        )}
      </section>

      <section className="block">
        <p className="label">Source reliability</p>
        <p className="block-note">
          Which sources are decision-critical depends on the tract: transit
          counts here only where households lack cars.
        </p>
        {Object.entries(detail.source_reliability).map(([source, reliability]) => (
          <MeterRow
            key={source}
            label={SOURCE_LABELS[source] ?? source}
            value={reliability.score}
            note={reliability.is_critical ? "decision-critical here" : undefined}
          />
        ))}
      </section>

      <section className="block">
        <p className="label">Evidence</p>
        <dl className="facts">
          <div>
            <dt>Heat index</dt>
            <dd className="numeric">
              {evidence.heat_index_f !== null ? `${evidence.heat_index_f}°F` : "no reading"}
            </dd>
          </div>
          <div>
            <dt>311 reports (60d)</dt>
            <dd className="numeric">{evidence.report_count.toLocaleString()}</dd>
          </div>
          <div>
            <dt>Transit feed age</dt>
            <dd className="numeric">
              {evidence.transit_feed_age_seconds !== null
                ? `${Math.round(evidence.transit_feed_age_seconds)}s`
                : "no feed"}
            </dd>
          </div>
          <div>
            <dt>Vulnerability (SVI)</dt>
            <dd className="numeric">
              {vulnerability.svi_overall !== null
                ? vulnerability.svi_overall.toFixed(3)
                : "suppressed by CDC"}
            </dd>
          </div>
        </dl>
      </section>
    </section>
  );
}
