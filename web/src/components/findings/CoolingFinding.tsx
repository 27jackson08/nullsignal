import { useEffect, useState } from "react";

import { fetchCoolingFinding, type CoolingFinding as Finding } from "../../lib/api";
import "../../styles/municipal.css";
import "./cooling-finding.css";

const PERCENT = (value: number) => `${Math.round(value * 100)}%`;

export function CoolingFinding() {
  const [data, setData] = useState<Finding | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCoolingFinding().then(setData).catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="record record-message">
        <p>The audit could not be loaded: {error}</p>
      </div>
    );
  }
  if (!data) {
    return <div className="record record-message"><p>Reading the audit…</p></div>;
  }

  const { sites, impact, equity, worst } = data;
  const zeroed = worst.filter((row) => row.working <= 0);

  return (
    <article className="record">
      <header className="record-masthead">
        <p className="record-issuer">
          <span className="civic">New York City</span>
          <span>Heat relief · coverage audit</span>
          <span>Sourced from NYC Open Data</span>
        </p>
        <h2 className="record-title">
          The city lists heat relief that does not work.
        </h2>
        <p className="record-standfirst">
          Every map of New York&rsquo;s cooling sites plots the locations and
          drops the status field. A broken spray shower becomes a dot that looks
          exactly like a working one &mdash; the absence of relief rendered as
          its presence.
        </p>
      </header>

      <div className="record-body">
        <section className="record-section">
          <h3>What the city publishes</h3>
          <p className="record-count">
            <span className="n fig">{sites.not_working}</span>
            <span className="of">
              of {sites.total.toLocaleString()} heat-relief sites are not
              operational
            </span>
          </p>
          <p className="record-lede">
            Not our judgement &mdash; the city&rsquo;s own{" "}
            <strong>status</strong> field. Every site below is published as
            relief and reports itself as unavailable.
          </p>

          <div className="record-table-wrap">
            <table className="record-table">
              <thead>
                <tr>
                  <th>Status, as published</th>
                  <th>Kind</th>
                  <th className="num">Sites</th>
                </tr>
              </thead>
              <tbody>
                {sites.by_status.map((row) => (
                  <tr key={`${row.kind}-${row.status}`}>
                    <td className="place">{row.status}</td>
                    <td className="quiet">
                      {row.kind === "spray_shower" ? "Spray shower" : "Cooling site"}
                    </td>
                    <td className="num fig">{row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="record-section">
          <h3>Who is standing inside the gap</h3>
          <p className="record-count">
            <span className="n fig">{impact.residents_overstated.toLocaleString()}</span>
            <span className="of">
              residents live within walking distance of relief that is listed
              and not working
            </span>
          </p>
          <p className="record-lede">
            Across <strong>{impact.tracts_overstated}</strong> census tracts.
            They appear covered on any map drawn from the site list. A further{" "}
            <strong>{impact.residents_without_relief.toLocaleString()}</strong>{" "}
            residents have no working relief within walking distance at all.{" "}
            {PERCENT(equity.overstated_top_quintile_share)} of the residents in
            the gap are in the most vulnerable fifth of the city, against{" "}
            {PERCENT(equity.citywide_top_quintile_share)} citywide &mdash;{" "}
            {equity.concentration.toFixed(2)}&times;.
          </p>
        </section>

        <section className="record-section">
          <h3>
            The worst of it{zeroed.length > 0 &&
              ` · ${zeroed.length} tracts with nothing working at all`}
          </h3>
          <div className="record-table-wrap">
            <table className="record-table">
              <colgroup>
                <col className="c-place" /><col className="c-boro" />
                <col className="c-num" /><col className="c-cover" />
              </colgroup>
              <thead>
                <tr>
                  <th>Tract</th>
                  <th>Borough</th>
                  <th className="num">Residents</th>
                  <th>Coverage, listed against working</th>
                </tr>
              </thead>
              <tbody>
                {worst.map((row) => (
                  <tr key={row.geoid}>
                    {/* Neighbourhood names repeat across tracts -- three
                        different parts of Sunset Park appear here -- so the
                        census number is what actually identifies the row. */}
                    <td className="place">
                      {row.name}
                      <span className="tract-no fig">
                        Tract {row.geoid.slice(-6)}
                      </span>
                    </td>
                    <td className="quiet">{row.borough}</td>
                    <td className="num fig">{row.population.toLocaleString()}</td>
                    <td>
                      <CoverageBars listed={row.listed} working={row.working} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <dl className="record-source">
          <dt>Sources</dt>
          <dd>
            NYC Open Data — cooling sites and spray showers, including the
            published <code>status</code> field. CDC/ATSDR Social Vulnerability
            Index 2022. US Census tract boundaries.
          </dd>
          <dt>Method</dt>
          <dd>
            Walking-distance buffers are unioned twice — once over every listed
            site, once over only those the city reports as operational — and
            each is intersected with tract geometry. The difference is the
            coverage a map would show that a resident would not find. A tract is
            counted only where that difference exceeds{" "}
            {PERCENT(0.05)} of its area, so a sliver at a buffer edge is not
            reported as a finding.
          </dd>
          <dt>What this does not claim</dt>
          <dd>
            That anyone was harmed, that the status field is current, or that
            any site is unattended. Only that the city publishes both facts and
            that most maps carry one of them.
          </dd>
        </dl>
      </div>
    </article>
  );
}

function CoverageBars({ listed, working }: { listed: number; working: number }) {
  const none = working <= 0;
  return (
    <div className="coverage">
      <div className="coverage-row coverage-listed">
        <span>Listed</span>
        <span className="coverage-track">
          <span className="coverage-fill" style={{ width: `${listed * 100}%` }} />
        </span>
        <span className="val fig">{PERCENT(listed)}</span>
      </div>
      <div className={none ? "coverage-row coverage-working is-zero" : "coverage-row coverage-working"}>
        <span>Working</span>
        <span className="coverage-track">
          <span className="coverage-fill" style={{ width: `${Math.max(working * 100, none ? 0 : 1)}%` }} />
        </span>
        <span className={none ? "val coverage-none" : "val fig"}>
          {none ? "None" : PERCENT(working)}
        </span>
      </div>
    </div>
  );
}
