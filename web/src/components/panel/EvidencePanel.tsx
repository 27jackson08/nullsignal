import { useZoneDetail } from "../../hooks/useZoneDetail";
import { STATE_META, isReassuring } from "../../lib/states";
import { MeterRow } from "./MeterRow";
import { VerificationQueue } from "../queue/VerificationQueue";
import "./evidence-panel.css";

interface EvidencePanelProps {
  geoid: string | null;
  onSelect: (geoid: string) => void;
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

/** Plain readings of the (world, regime) hypothesis keys. */
const HYPOTHESIS_LABELS: Record<string, string> = {
  "normal/faithful": "Nothing unusual",
  "normal/blind": "Looks normal, but we cannot see transit",
  "heat/faithful": "Dangerous heat, mobility intact",
  "heat/blind": "Dangerous heat, transit unverified",
  "heat_stranded/faithful": "Heat and transit failure — people stranded",
  "heat_stranded/blind": "Stranded, and hidden from us",
  "local_fault/faithful": "Localised infrastructure fault",
  "local_fault/blind": "Local fault, transit unverified",
};

const UNLOCK_DAY: Record<string, string> = {
  entropy: "Bayesian layer",
  contradiction: "Contradiction graph",
};

/** What a tract's reporting level means for how its silence should be read. */
function describeReporting(index: number): string {
  if (index < 0.8) {
    return "This tract reports less than a comparable one, so hearing nothing "
      + "from it is weak evidence that nothing is wrong.";
  }
  if (index > 1.25) {
    return "This tract reports readily, so silence here is genuinely informative.";
  }
  return "This tract reports at about the typical rate.";
}

export function EvidencePanel({ geoid, onSelect }: EvidencePanelProps) {
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
          <VerificationQueue onSelect={onSelect} />
        </div>
      </section>
    );
  }

  const meta = STATE_META[detail.state];
  const baselineMeta = STATE_META[detail.baseline_state];
  const overclaimed = isReassuring(detail.baseline_state) && !isReassuring(detail.state);
  const { sufficiency, evidence, vulnerability, reporting, contradictions } = detail;
  const nextCheck = detail.recommended_checks[0];

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

      <div className="explanation">
        <p>{detail.explanation.text}</p>
        <p className="explanation-source">
          {detail.explanation.source === "generated"
            ? "Written by a language model from the evidence packet; every figure verified against it."
            : "Written deterministically from the evidence packet."}
          {detail.explanation.note && ` (${detail.explanation.note})`}
        </p>
      </div>

      {contradictions.length > 0 && (
        <div className="contradictions">
          <p className="label">Sources disagree</p>
          <ul>{contradictions.map((line) => <li key={line}>{line}</li>)}</ul>
          <p className="contradiction-note">
            Conflicts widen the doubt rather than being averaged away &mdash;
            the risk estimate is unchanged, the confidence in it is not.
          </p>
        </div>
      )}

      {nextCheck && (
        <div className="next-check">
          <p className="label">Highest-value next check</p>
          <p className="check-label">{nextCheck.label}</p>
          <p className="check-detail">{nextCheck.detail}</p>
          <dl className="check-meta">
            <div><dt>Time</dt><dd className="numeric">{nextCheck.latency_minutes} min</dd></div>
            <div><dt>Value per cost</dt><dd className="numeric">{nextCheck.value_per_cost.toFixed(1)}&times;</dd></div>
            <div><dt>Response now</dt><dd>{detail.decision}</dd></div>
          </dl>
        </div>
      )}

      <section className="block">
        <p className="label">What might be happening</p>
        {detail.posterior.map((row) => (
          <MeterRow key={row.hypothesis}
                    label={HYPOTHESIS_LABELS[row.hypothesis] ?? row.hypothesis}
                    value={row.probability} />
        ))}
        {detail.unseen_danger > 0.02 && (
          <p className="block-note unseen">
            {(detail.unseen_danger * 100).toFixed(0)}% of the belief sits in
            scenarios where something is wrong <em>and</em> the instruments are
            not showing it.
          </p>
        )}
      </section>

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
        <p className="label">Reporting behaviour</p>
        {reporting.estimated ? (
          <>
            <dl className="facts">
              <div>
                <dt>Reporting index</dt>
                <dd className="numeric">{reporting.index?.toFixed(2)}&times; typical</dd>
              </div>
              <div>
                <dt>Weight of its silence</dt>
                <dd className="numeric">{reporting.evidential_weight?.toFixed(2)}</dd>
              </div>
            </dl>
            <p className="block-note">{describeReporting(reporting.index ?? 1)}</p>
          </>
        ) : (
          <p className="block-note">{reporting.note}</p>
        )}
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
            <dt>Heat relief reachable</dt>
            <dd className="numeric">
              {detail.heat_relief.reachable !== null
                ? `${Math.round(detail.heat_relief.reachable * 100)}% of tract`
                : "unknown"}
            </dd>
          </div>
          {(detail.heat_relief.overstated ?? 0) > 0.05 && (
            <div>
              <dt>&hellip; listed but not working</dt>
              <dd className="numeric overstated">
                {Math.round((detail.heat_relief.overstated ?? 0) * 100)}%
              </dd>
            </div>
          )}
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
