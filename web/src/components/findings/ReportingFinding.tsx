import { useEffect, useState } from "react";

import { fetchReportingFinding } from "../../lib/api";
import type { ComplaintShare, ReportingFinding as Finding } from "../../lib/api";
import "../../styles/municipal.css";
import "./cooling-finding.css";
import "./reporting-finding.css";

const PCT = (v: number) => `${(v * 100).toFixed(2)}%`;

/** Titles arrive in two conventions: HPD shouts, other agencies do not. */
function tidy(kind: string): string {
  if (kind !== kind.toUpperCase()) return kind;
  return kind.charAt(0) + kind.slice(1).toLowerCase();
}

export function ReportingFinding() {
  const [data, setData] = useState<Finding | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchReportingFinding().then(setData).catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return <div className="record record-message"><p>Unavailable: {error}</p></div>;
  }
  if (!data) {
    return <div className="record record-message"><p>Reading 311…</p></div>;
  }

  const { volume_by_quintile, over_represented, under_represented, heat_channels } = data;
  const peak = Math.max(...volume_by_quintile.map((v) => v.per_thousand));

  return (
    <article className="record">
      <header className="record-masthead">
        <p className="record-issuer">
          <span className="civic">New York City</span>
          <span>311 &middot; what it can and cannot tell you</span>
          <span>{data.total_reports.toLocaleString()} requests</span>
        </p>
        <h2 className="record-title">
          Everyone calls 311. They don&rsquo;t call about the same things.
        </h2>
        <p className="record-standfirst">
          Reading complaint volume as a hardship signal assumes that people in
          trouble call more. Across New York they call at nearly the same rate
          &mdash; and about entirely different subjects.
        </p>
      </header>

      <div className="record-body">
        <section className="record-section">
          <h3>Volume barely moves</h3>
          <p className="record-lede">
            Calls per thousand residents, from the least to the most vulnerable
            fifth of the city. The whole range spans{" "}
            <strong>{data.volume_ratio.toFixed(2)}&times;</strong>.
          </p>
          <ol className="volume">
            {volume_by_quintile.map((v) => (
              <li key={v.quintile}>
                <span className="volume-q">
                  {v.quintile === 1 ? "Least vulnerable"
                    : v.quintile === 5 ? "Most vulnerable" : `Q${v.quintile}`}
                </span>
                <span className="volume-bar">
                  <span style={{ width: `${(v.per_thousand / peak) * 100}%` }} />
                </span>
                <span className="volume-val fig">{v.per_thousand.toFixed(1)}</span>
              </li>
            ))}
          </ol>
        </section>

        <section className="record-section">
          <h3>The mix moves enormously</h3>
          <p className="record-lede">
            Each type&rsquo;s share of that quintile&rsquo;s own calls, so
            differences in volume are already divided out. What is left is
            subject matter.
          </p>
          <Mix
            caption="The most vulnerable fifth calls about the inside of the home"
            rows={over_represented}
            tone="high"
          />
          <Mix
            caption="The least vulnerable fifth calls about the world outside it"
            rows={under_represented}
            tone="low"
          />
        </section>

        <section className="record-section">
          <h3>And there is no channel for the hazard</h3>
          <p className="record-lede">
            This window runs through August. Every heat-adjacent complaint type
            the taxonomy offers means something other than a resident
            overheating:
          </p>
          <div className="record-table-wrap">
            <table className="record-table">
              <thead>
                <tr>
                  <th scope="col">Complaint type</th>
                  <th scope="col">What it actually reports</th>
                  <th scope="col" className="num">Requests</th>
                </tr>
              </thead>
              <tbody>
                {heat_channels.map((c) => (
                  <tr key={c.kind}>
                    <td className="place">{tidy(c.kind)}</td>
                    <td className="quiet">{c.means}</td>
                    <td className="num fig">{c.reports.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="record-lede mix-verdict">
            A New Yorker whose apartment is dangerously hot has nowhere to file
            it. A heat-response system reading 311 for distress is reading a
            form with no box for the thing it is looking for.
          </p>
        </section>

        <dl className="record-source">
          <dt>Why this shapes the engine</dt>
          <dd>
            It is the reason reporting is read as <em>tempo</em> &mdash; a
            tract against its own long-run rate &mdash; and never as an
            absolute hardship measure. A tract going quieter than itself is
            information. A tract that is quieter than the city next door is a
            demographic fact about who calls 311 and about what.
          </dd>
          <dt>Sources and method</dt>
          <dd>
            NYC 311 service requests, {data.window.start?.slice(0, 10)} to{" "}
            {data.window.end?.slice(0, 10)}, joined to census tracts by point
            in polygon and grouped by CDC/ATSDR Social Vulnerability Index
            quintile. Only complaint types with at least 900 requests are
            compared, so a share is never computed from a handful of calls.
          </dd>
          <dt>What this does not claim</dt>
          <dd>
            That any neighbourhood reports too much or too little, or that the
            mix is anyone&rsquo;s fault. Only that complaint volume and
            complaint subject are different measurements, and that a system
            treating the first as a proxy for hardship is not measuring what it
            believes.
          </dd>
        </dl>
      </div>
    </article>
  );
}

function Mix({ caption, rows, tone }: {
  caption: string; rows: ComplaintShare[]; tone: "high" | "low";
}) {
  const widest = Math.max(
    ...rows.map((r) => Math.max(r.least_vulnerable_share, r.most_vulnerable_share)),
  );
  return (
    <div className="mix">
      <p className="mix-caption">{caption}</p>
      <ul>
        {rows.map((r) => (
          <li key={r.kind}>
            <span className="mix-kind">{tidy(r.kind)}</span>
            <span className="mix-pair">
              <span className="mix-track">
                <span className="mix-fill least"
                      style={{ width: `${(r.least_vulnerable_share / widest) * 100}%` }} />
              </span>
              <span className="mix-track">
                <span className={`mix-fill most ${tone}`}
                      style={{ width: `${(r.most_vulnerable_share / widest) * 100}%` }} />
              </span>
            </span>
            <span className="mix-vals fig">
              {PCT(r.least_vulnerable_share)} &rarr; {PCT(r.most_vulnerable_share)}
            </span>
            <span className="mix-ratio fig">{r.ratio.toFixed(2)}&times;</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
