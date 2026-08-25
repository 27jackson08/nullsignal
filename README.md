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

## Inference

A hypothesis is a *pair*: what is happening, and whether we can see it.

    hypothesis = (world state, observation regime)

Four worlds x two regimes = eight hypotheses, so the posterior is computed by
enumeration — exact, and every number traceable to a prior, a likelihood entry
and a reliability score.

Splitting the pair is the point. A conventional system reasons only over world
states, so it has no way to represent "this may be bad *and* my feeds may be
lying about it" and can never conclude it might be blind. Here
`(heat_stranded, blind)` is a cell the engine can raise probability on.

Two mechanics carry it:

- **A blind regime makes the instruments agree with nothing.** A frozen feed
  does not emit noise, it replays its last good state — so P(see "normal" |
  transit failed, blind) is *high*. That asymmetry is what a threshold on the
  feed's own values can never reach.
- **Unreliable evidence cannot move the posterior.** Each likelihood is mixed
  toward uniform in proportion to that source's reliability, so as it goes to
  zero the observation stops discriminating. Missing data does not push toward
  safe; it does not push at all. Asserted as an invariant: KL(posterior ‖ prior)
  decays monotonically to zero.

The regime is scoped to the mobility channel. Modelled globally, a dead subway
feed also discredited the forecast, and risk *fell* as the engine went blind.

## Deciding what to check next

Exact EVPI over five concrete checks and three responses — small enough to
enumerate, so every ranking is reproducible.

**VOI answers "which check", not "which zone".** It is deliberately not
monotone in stakes: information is worth most near a decision boundary and
nothing once one response dominates whatever the answer is. Ranking zones by
VOI would put the clearest emergencies last.

Zones are queued by **unresolved harm** — believed harm weighted by remaining
doubt — which *is* monotone in both vulnerability and uncertainty. That is
where equity enters the ordering, structurally rather than as a reweighting,
and it is asserted as an invariant.

Response costs are derived from the risk thresholds rather than hand-set, so a
tract can never read "confirmed low" beside advice to send crews.

## The scoreboard

```bash
uv run nullsignal eval                    # canonical scenario, ~7s
uv run nullsignal eval --list             # all scenarios
```

Both engines see identical corrupted evidence; neither sees ground truth. The
scenario holds *what is true* and *what breaks in our ability to see it* apart,
which is what makes a run a measurement rather than a demonstration.

**heatwave-transit-silent-failure** — heat reaches the low nineties, below any
advisory threshold. The transit feed freezes (HTTP 200, plausible payload,
normal service). Two hours later service actually stops and 311 reporting
collapses. No single reading crosses a threshold; the danger is the combination.

| engine | false reassurance | residents | false alarm | warning |
| --- | --- | --- | --- | --- |
| baseline | **83.1%** | 3,889,567 | 8.7% | 0h |
| NullSignal | **0.0%** | 0 | 23.8% | **2h** |

> **50.7%** of the residents the conventional dashboard kept calling safe are in
> the most vulnerable quintile, against **40.2%** citywide — **1.26x**.

The two hours are the point: NullSignal stops confirming safety when the feed
freezes, not when the harm arrives. It knows it has gone blind before there is
anything to see.

### Across five scenarios

| Scenario | Baseline | NullSignal |
| --- | --- | --- |
| heatwave, silent transit failure | 83.1% | **0.0%** |
| honest outage (feed stops answering) | 83.1% | **0.0%** |
| reporting collapse | 0.0% * | **5.1%** |
| sensor drift, one station | 15.2% * | **5.7%** |
| sensor drift, every station | 83.1% | 96.6% |

\* Stopped clocks: those two baseline figures are bought by alarming 60% and
65% of the time when nothing is wrong. The report flags them rather than
letting the comparison stand.

### Where it still loses

**sensor-drift-masking-heat — beaten, 96.6% against 83.1%, and it stays in the
suite.** When *every* station drifts the same way there is nothing left to
disagree with, and catching it needs an external reference the system does not
have. A single drifting station is caught (see below); a uniformly wrong
instrument is not, and the test suite asserts that limit explicitly rather than
letting it be quietly assumed away.

## Cross-source agreement

Some faults leave no trace in any single feed. A thermometer drifting a few
degrees per hour defeats every liveness detector by construction: the payload
changes, the clock advances, each reading is individually defensible. The only
thing wrong is the *sequence*.

What is visible is disagreement with neighbouring stations. New York's five
borough gridpoints normally agree closely — mean spread 1.9°F, 95th percentile
3.0°F — so the outlier threshold sits at 5°F, above real weather variation
across the city. A station several degrees from its peers loses reliability;
one that agrees does not.

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

## Inference

A hypothesis is a *pair*: what is happening, and whether we can see it.

    hypothesis = (world state, observation regime)

Four worlds x two regimes = eight hypotheses, so the posterior is computed by
enumeration — exact, and every number traceable to a prior, a likelihood entry
and a reliability score.

Splitting the pair is the point. A conventional system reasons only over world
states, so it has no way to represent "this may be bad *and* my feeds may be
lying about it" and can never conclude it might be blind. Here
`(heat_stranded, blind)` is a cell the engine can raise probability on.

Two mechanics carry it:

- **A blind regime makes the instruments agree with nothing.** A frozen feed
  does not emit noise, it replays its last good state — so P(see "normal" |
  transit failed, blind) is *high*. That asymmetry is what a threshold on the
  feed's own values can never reach.
- **Unreliable evidence cannot move the posterior.** Each likelihood is mixed
  toward uniform in proportion to that source's reliability, so as it goes to
  zero the observation stops discriminating. Missing data does not push toward
  safe; it does not push at all. Asserted as an invariant: KL(posterior ‖ prior)
  decays monotonically to zero.

The regime is scoped to the mobility channel. Modelled globally, a dead subway
feed also discredited the forecast, and risk *fell* as the engine went blind.

## Deciding what to check next

Exact EVPI over five concrete checks and three responses — small enough to
enumerate, so every ranking is reproducible.

**VOI answers "which check", not "which zone".** It is deliberately not
monotone in stakes: information is worth most near a decision boundary and
nothing once one response dominates whatever the answer is. Ranking zones by
VOI would put the clearest emergencies last.

Zones are queued by **unresolved harm** — believed harm weighted by remaining
doubt — which *is* monotone in both vulnerability and uncertainty. That is
where equity enters the ordering, structurally rather than as a reweighting,
and it is asserted as an invariant.

Response costs are derived from the risk thresholds rather than hand-set, so a
tract can never read "confirmed low" beside advice to send crews.

## The scoreboard

```bash
uv run nullsignal eval                    # canonical scenario, ~7s
uv run nullsignal eval --list             # all scenarios
```

Both engines see identical corrupted evidence; neither sees ground truth. The
scenario holds *what is true* and *what breaks in our ability to see it* apart,
which is what makes a run a measurement rather than a demonstration.

**heatwave-transit-silent-failure** — heat reaches the low nineties, below any
advisory threshold. The transit feed freezes (HTTP 200, plausible payload,
normal service). Two hours later service actually stops and 311 reporting
collapses. No single reading crosses a threshold; the danger is the combination.

| engine | false reassurance | residents | false alarm | warning |
| --- | --- | --- | --- | --- |
| baseline | **83.1%** | 3,889,567 | 8.7% | 0h |
| NullSignal | **0.0%** | 0 | 23.8% | **2h** |

> **50.7%** of the residents the conventional dashboard kept calling safe are in
> the most vulnerable quintile, against **40.2%** citywide — **1.26x**.

The two hours are the point: NullSignal stops confirming safety when the feed
freezes, not when the harm arrives. It knows it has gone blind before there is
anything to see.

### Where it loses

A scoreboard that only shows wins is a slide. Two of four scenarios are
uncomfortable, and the tool says so in its own output:

- **sensor-drift-masking-heat** — *NullSignal is beaten, 96.6% against 83.1%.*
  A thermometer drifting a few degrees per hour defeats every liveness
  detector by construction: the payload changes, the clock advances, each
  reading is defensible. With one weather source per borough there is no
  redundancy to catch it. The fix is cross-source disagreement, not another
  detector.
- **reporting-collapse** — the baseline scores 0% false reassurance by alarming
  60% of the time when nothing is wrong. A stopped clock. NullSignal takes
  31.4% against a 15.4% false-alarm rate; the report flags the comparison
  rather than claiming the win.

## Explanation

The language model never sees the verdict. The evidence packet it receives has
no risk score, no decision state, and no recommendation about safety — handing
a model the conclusion and asking it to justify the conclusion produces fluent
advocacy for whatever it was handed, including when that is wrong.

Two independent guards on the prose:

- **Placeholder mode.** The model never writes a number. It writes `{{field}}`
  slots naming packet values and the application substitutes them afterwards.
  A fabricated figure is not *caught* — it is structurally impossible, because
  the model has no channel through which to emit one. Unknown field names are
  rejected.
- **Numeric verification.** Substituted output is checked anyway: every numeric
  token must trace to the packet, or the whole explanation is discarded.

Either failure falls back to the deterministic template, so the worst case is
duller prose rather than confident fiction. That template is the guaranteed
floor, not a degraded mode — it needs no key, no network, and no model, and a
dead credential cannot leave an operator without an account of why a tract was
flagged. Set `ANTHROPIC_API_KEY` to enable the generated path.

Explanations cache on a packet fingerprint, so identical evidence yields the
identical sentence.

## The six invariants

These are the product specification. All six are implemented and passing.

```
test_silence_never_confirms_safe            zero evidence -> UNKNOWN, never CONFIRMED_LOW
test_contradiction_widens_not_averages      conflicts lower sufficiency, never move risk
test_stale_source_cannot_move_posterior     KL(posterior || prior) decays to zero
test_equity_monotonicity                    evidence fixed, higher SVI ranks higher
test_silent_failure_beats_baseline          zero false reassurance, 2h of warning
test_llm_emits_no_unsupported_numbers       every figure traces to the packet
```

```
make test      # 151 tests
make coverage  # 81% line coverage
make check     # tests + typecheck + production build
make demo      # engine on :8000, map on :5173
```

## Accessibility

The map is a canvas, which conveys nothing on its own, so operability is built
rather than inherited:

- **Keyboard navigation is spatial.** Arrow keys move to the nearest tract in
  that direction, Enter opens it, Escape clears. A tab order down an
  alphabetical list would be technically operable and useless for understanding
  geography, which is the whole point of the view.
- **A live region carries the verdict.** Focus movement announces neighbourhood,
  borough, state and population — the only channel a screen reader has here.
- **Contrast is measured, not assumed.** State fills run 3.2–7.9:1 against the
  map ground; text runs 5.1–15:1. The faint token was 3.4:1 and failed AA for
  the size it is used at; it is now 5.7:1.
- Motion is disabled under `prefers-reduced-motion`, and focus is always visible.

Verified at 320, 375, 768, 1024, 1440 and 1920 by rendering the app in a
same-origin iframe at each width — media queries respond to an iframe as they
do to a viewport. A static CSS audit had missed a 67px overflow at 320px, where
the header could not fit the brand alongside four view buttons and stretched
the whole shell.

## Security headers

Every response carries `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy`, `Permissions-Policy`, a `default-src 'none'` CSP, and
`Cache-Control: no-store` — this service answers with JSON and nothing else,
and each response names a neighbourhood at a moment, neither of which is public
or stays true.

HSTS is emitted **only over TLS**. Sending it over plain HTTP is ignored at
best, and harmful if the config reaches a host that cannot serve HTTPS.

## Status

Complete: 7 of 7 days. See `docs/PLAN.md`.

The suite doubles as a build progress meter: invariants for components not yet
built are skipped with the day they unlock, rather than quietly passing.

```
make test
```
