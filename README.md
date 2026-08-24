# NullSignal

**Don't confuse silence with safety.**

Most monitoring systems encode *no data* as *no problem*. NullSignal makes
"we don't know" a first-class state that "low risk" cannot collapse into.

## The 2x2

|                      | Sufficiency low | Sufficiency high |
| -------------------- | --------------- | ---------------- |
| **Risk estimate low**  | `UNKNOWN`       | `CONFIRMED_LOW`  |
| **Risk estimate high** | `SUSPECTED`     | `CONFIRMED_HIGH` |

`CONFIRMED_LOW` requires low risk **and** high sufficiency. Silence can never
produce green. See `engine/src/nullsignal/decision.py`.

## Run it

```bash
make setup
make snapshot     # ~2 min, pulls real NYC data into data/raw
make build        # builds data/nullsignal.duckdb
make demo         # engine on :8000, map on :5173
```

## Data sources

All keyless except where noted. Verified 2026-08-24.

| Source | Dataset | Notes |
| --- | --- | --- |
| NYC 311 | Socrata `erm2-nwe9` | ~99% geocoded |
| Census tracts | Socrata `63ge-mke6` | 2,325 tracts, joins to SVI on `geoid` |
| CDC SVI 2022 | `svi.cdc.gov` | tract-level vulnerability |
| MTA GTFS-RT | `api-endpoint.mta.info` | protobuf, 7 subway feeds |
| NWS | `api.weather.gov` | **403s without a contact email in User-Agent** |

Snapshots are committed so the demo runs offline and the evaluation is
reproducible.

## Rendering

The map is `d3-geo` projecting onto a `<canvas>`, with an offscreen colour-index
buffer for hit testing (constant cost regardless of tract count). Two earlier
approaches were tried and rejected:

- **MapLibre GL** — its Web Worker never completes its handshake in this setup
  (reproduced on v5 and v6, dev and production builds, normal and CSP builds),
  so layers render but no source ever parses. With no basemap in the design,
  MapLibre's tile streaming was unused anyway.
- **SVG paths** — 2,325 DOM nodes made every view switch re-render the tree.

Canvas: ~1 ms per view switch, 64 DOM nodes, no long tasks.

## Silent-failure detection

A feed can be up and semantically dead: HTTP 200, correct content type,
plausible payload, nothing behind it changing. Three detectors, run against
poll history rather than a single snapshot:

| Detector | Catches |
| --- | --- |
| `cadence_violation` | the feed's own clock has stopped advancing |
| `content_flatline` | payload byte-identical for longer than its publish interval |
| `value_flatline` | a reading pinned at one plausible constant |

Combined with `max`, not a sum: a frozen feed trips several at once, but that
is one fact seen three ways.

Two rules keep them honest, both learned the hard way:

- **Duration, not poll count.** Counting identical polls flags any feed polled
  faster than it publishes — an hourly forecast sampled every 30s is always
  byte-identical and perfectly healthy.
- **Lag at poll time, not against now.** Measuring against wall-clock conflates
  "the feed stopped" with "we stopped polling", so every feed looked dead
  minutes after a poll run ended.

Detectors that cannot run report as *not checked*, never as passing.

## Reporting bias

311 report counts are not incident counts. Propensity is estimated from the
structure of *what* a tract reports, not how much:

```
log rate(zone, category) = alpha(category) + beta(zone) + delta(zone, category)
```

`beta` is the component common to every category, so a tract that reports
unusually much across all of them is a high-propensity tract, while a spike
confined to one category stays in the residual as hazard. Deliberately no
vulnerability covariates: regressing reports on SVI would let the model absorb
"more vulnerable means fewer reports" as an expected pattern and fit away the
exact bias it exists to measure.

The output feeds one thing — **what a tract's silence is worth**. South
Williamsburg files 9 reports in 60 days for 5,991 residents (index 0.16), so its
311 coverage drops to 0.11. Hearing nothing from it is close to no information.

### What the data actually says

Testing the premise honestly: **NYC 311 propensity does not fall with
vulnerability.** It is flat across SVI quintiles (correlation +0.04), and
composite evidence availability is *higher* for more vulnerable tracts, which
are denser and better served by transit.

The real finding is sharper:

> **70.7% of residents in evidence blind spots are in the most vulnerable
> quintile, against 24.3% citywide** — 2.9x over-representation.

It is not that vulnerable neighbourhoods are systematically less visible. It is
that where the system goes blind, it goes blind about the people who can least
afford it: 207,067 residents, 146,376 of them in the top SVI quintile.

## Contradictions

Conflicts are never fused. Averaging "transit halted" with "transit normal"
into "mildly degraded" would launder a crisis into a shrug. A contradiction
lowers *sufficiency* and leaves the risk estimate untouched — a disagreement is
not a measurement.

The rule that earns the propensity model its keep: dangerous heat with falling
complaint volume is a contradiction **only where silence is worth reading**.
Two guards keep it informative:

- **Tempo, not absolute rate.** Measured against a tract's own longer-run rate.
  A fixed cut per 1,000 residents sits above or below almost the whole city, so
  it fired on 94% of tracts — a contradiction that fires everywhere says nothing.
- **Only tracts whose quiet is meaningful.** Where a tract barely reports at
  all, quiet is the normal condition.

At 83°F: 0 contradictions. Under a simulated 104°F: 425 tracts (18.3%).

## Status

Day 3 of 7. See `docs/PLAN.md`.

The suite doubles as a build progress meter: invariants for components not yet
built are skipped with the day they unlock, rather than quietly passing.

```
make test
```
