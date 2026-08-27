import { useEffect, useState } from "react";

import { fetchBriefing, fetchCoolingFinding } from "../../lib/api";
import type { Assignment, Briefing, CoolingFinding } from "../../lib/api";
import { useCompletedChecks, type Outcome } from "../../hooks/useCompletedChecks";
import "../../styles/municipal.css";
import "./shift-briefing.css";

const PERCENT = (v: number) => `${Math.round(v * 100)}%`;

/** Reasons arrive from two layers: missing sources read as clauses, conflicts
 *  read as sentences. In a dashed list they have to agree, so the leading
 *  capital and the trailing stop both come off -- unless the first word is an
 *  initialism, which lowercasing would mangle. */
function asClause(reason: string): string {
  const trimmed = reason.replace(/\.$/, "");
  const startsWithInitialism = /^[A-Z]{2,}/.test(trimmed);
  return startsWithInitialism
    ? trimmed
    : trimmed.charAt(0).toLowerCase() + trimmed.slice(1);
}

function issuedLabel(iso: string | null): string {
  if (!iso) return "Issued from the committed snapshot";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "Issued from the committed snapshot";
  return at.toLocaleString(undefined, {
    day: "numeric", month: "long", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export function ShiftBriefing({ onOpenAudit }: { onOpenAudit: () => void }) {
  const [data, setData] = useState<Briefing | null>(null);
  const [audit, setAudit] = useState<CoolingFinding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { completed, record, undo, clear } = useCompletedChecks();

  useEffect(() => {
    fetchBriefing().then(setData).catch((e: Error) => setError(e.message));
    // The audit is what makes the most common assignment worth doing, so the
    // briefing quotes it. Its absence must not stop the work order printing.
    fetchCoolingFinding().then(setAudit).catch(() => setAudit(null));
  }, []);

  if (error) {
    return <div className="record record-message"><p>Briefing unavailable: {error}</p></div>;
  }
  if (!data) {
    return <div className="record record-message"><p>Preparing the briefing…</p></div>;
  }

  const { situation, assignments, check_tally } = data;
  const headCheck = check_tally[0];

  // A tract counts as cleared once a check has come back clear: the engine
  // already computed what it becomes, so this only reads that answer.
  const cleared = assignments.filter(
    (a) => completed[a.geoid] === "clear"
      && a.check?.resolves_to.state !== "UNKNOWN",
  );
  const outstanding = assignments.filter((a) => !cleared.includes(a));
  const residentsCleared = cleared.reduce((sum, a) => sum + a.population, 0);
  const hours = Math.round(data.minutes_to_clear_the_city / 60);

  return (
    <article className="record briefing">
      <header className="record-masthead">
        <p className="record-issuer">
          <span className="civic">New York City</span>
          <span>Evidence briefing &middot; heat</span>
          <span>{issuedLabel(data.issued_at)}</span>
        </p>
        <h2 className="record-title">Where to send people tonight.</h2>
        <p className="record-standfirst">
          Ranked by the residents behind each unresolved call &mdash; not by
          risk. A tract we understand needs no visit however bad it is; a tract
          we cannot see does, and the people standing in it are the reason.
        </p>
        <div className="order-actions">
          <button type="button" className="print-order" onClick={() => window.print()}>
            Print this order
          </button>
          {Object.keys(completed).length > 0 && (
            <button type="button" className="reset-order" onClick={clear}>
              Reset the shift
            </button>
          )}
        </div>
      </header>

      <div className="record-body">
        <section className="record-section">
          <h3>Situation</h3>
          <div className="situation">
            <p className="situation-figure">
              <span className="n fig">{situation.uncertifiable_tracts}</span>
              <span className="of">tracts cannot be called either way</span>
            </p>
            <p className="situation-figure">
              <span className="n fig">
                {situation.uncertifiable_residents.toLocaleString()}
              </span>
              <span className="of">residents live in them</span>
            </p>
            <p className="situation-figure">
              <span className="n fig">{situation.concentration.toFixed(2)}&times;</span>
              <span className="of">
                over-represented: {PERCENT(situation.top_quintile_share)} of them
                are in the most vulnerable fifth of the city, against{" "}
                {PERCENT(situation.citywide_top_quintile_share)} citywide
              </span>
            </p>
          </div>
        </section>

        {headCheck && (
          <section className="record-section">
            <h3>Why we ask you to confirm rather than assume</h3>
            <p className="record-lede">
              <strong>{headCheck.tracts}</strong> of those tracts resolve on the
              same action &mdash; <strong>{headCheck.check.toLowerCase()}</strong>{" "}
              &mdash; covering{" "}
              <strong>{headCheck.residents.toLocaleString()}</strong> residents at{" "}
              {headCheck.minutes} minutes each.
              {audit && (
                <>
                  {" "}That check is not a formality:{" "}
                  <strong>{audit.sites.not_working}</strong> of the city&rsquo;s{" "}
                  {audit.sites.total.toLocaleString()} listed heat-relief sites
                  report themselves as not working, and{" "}
                  {audit.impact.residents_overstated.toLocaleString()} residents
                  live inside relief that exists on paper and not in fact.{" "}
                  <button type="button" className="inline-link" onClick={onOpenAudit}>
                    Read the audit
                  </button>
                  .
                </>
              )}
            </p>
          </section>
        )}

        <section className="record-section">
          <h3>
            Assignments &middot; {outstanding.length} outstanding
            {cleared.length > 0 && ` \u00b7 ${cleared.length} cleared`}
          </h3>
          {cleared.length > 0 && (
            <p className="cleared-note">
              <strong>{residentsCleared.toLocaleString()}</strong> residents are
              no longer standing in a blind spot. The engine can call these
              tracts now &mdash; not because anything changed on the ground, but
              because somebody went and looked.
            </p>
          )}
          <ol className="assignments">
            {assignments.map((a) => (
              <AssignmentRow
                key={a.geoid}
                assignment={a}
                outcome={completed[a.geoid]}
                onRecord={(outcome) => record(a.geoid, outcome)}
                onUndo={() => undo(a.geoid)}
              />
            ))}
          </ol>
          <p className="clear-city">
            Every blind spot in New York clears in roughly{" "}
            <strong>{hours} crew-hours</strong>. Treating doubt as actionable is
            usually objected to on the grounds that it does not scale. This is
            what it would cost.
          </p>
        </section>

        <dl className="record-source">
          <dt>How this list was ordered</dt>
          <dd>
            By expected residents at stake: the harm still unresolved for a
            tract, weighted by the doubt remaining on it, multiplied by the
            people it would fall on. Ranking on the per-capita figure alone put
            empty parkland and a cemetery at the top &mdash; a tract with nobody
            in it can be exactly as unresolved as a dense one, and the
            arithmetic could not tell them apart.
          </dd>
          <dt>What this list is not</dt>
          <dd>
            It is not a ranking of danger. Every tract here is one we cannot
            call either way; a tract we understand to be dangerous belongs in a
            response plan, not in a verification queue.
          </dd>
        </dl>
      </div>
    </article>
  );
}


function AssignmentRow({ assignment, outcome, onRecord, onUndo }: {
  assignment: Assignment;
  outcome: Outcome | undefined;
  onRecord: (outcome: Outcome) => void;
  onUndo: () => void;
}) {
  const a = assignment;
  const resolved = outcome === "clear" && a.check?.resolves_to.state !== "UNKNOWN";
  const found = outcome === "problem";

  return (
    <li className={`assignment${resolved ? " is-cleared" : ""}${found ? " is-flagged" : ""}`}>
      <span className={`tick${outcome ? " is-done" : ""}`} aria-hidden="true" />
      <span className="rank fig">{String(a.rank).padStart(2, "0")}</span>

      <div className="where">
        <p className="place">{a.name}</p>
        <p className="meta">
          {a.borough} &middot; Tract {a.geoid.slice(-6)} &middot;{" "}
          <span className="fig">{a.population.toLocaleString()}</span> residents
        </p>
      </div>

      <div className="why">
        {resolved && a.check ? (
          <>
            <p className="why-label">Now</p>
            <p className="resolved-state">
              Confirmed low &middot; sufficiency{" "}
              <span className="fig">{a.sufficiency.toFixed(2)}</span> &rarr;{" "}
              <span className="fig">{a.check.resolves_to.sufficiency.toFixed(2)}</span>
            </p>
          </>
        ) : (
          <>
            <p className="why-label">{found ? "Reported back" : "Blind because"}</p>
            {found ? (
              <p className="flagged-state">
                A problem was found. This is no longer a question of evidence
                &mdash; it belongs in a response plan.
              </p>
            ) : (
              <ul>
                {a.blind_because.map((reason) => (
                  <li key={reason}>{asClause(reason)}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      <div className="action">
        {a.check ? (
          <>
            <p className="do">{a.check.label}</p>
            <p className="meta">
              <span className="fig">{a.check.minutes}</span> min &middot;{" "}
              {a.check.detail}
            </p>
            {a.also_worth_doing && !outcome && (
              <p className="meta also">
                Also worth doing: {a.also_worth_doing.label.toLowerCase()} (
                <span className="fig">{a.also_worth_doing.minutes}</span> min)
                &mdash; it would not settle the call, but it would most change
                the response.
              </p>
            )}
            {outcome ? (
              <button type="button" className="undo" onClick={onUndo}>
                Undo
              </button>
            ) : (
              <p className="report">
                <button type="button" onClick={() => onRecord("clear")}>
                  Came back clear
                </button>
                <button type="button" onClick={() => onRecord("problem")}>
                  Found a problem
                </button>
              </p>
            )}
          </>
        ) : (
          <p className="do">No check resolves this from here</p>
        )}
      </div>
    </li>
  );
}
