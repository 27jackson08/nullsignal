# NullSignal

**Don't confuse silence with safety.**

Most monitoring systems encode *no data* as *no problem*. NullSignal makes
"we don't know" a first-class state that "low risk" cannot collapse into.

**[Open it →](https://27jackson08.github.io/nullsignal/)** — no install, no
backend. The published site is the same build a local clone produces: every
response is baked from the snapshot committed in `data/raw`, so what you click
is exactly what `make demo` serves.

Three surfaces, in the order they matter:

| | |
| --- | --- |
| **Tonight's briefing** | Where to send people, why, and what to do there. The part someone uses. |
| **Heat relief audit** | 100 of New York's 1,026 listed cooling sites report themselves as not working. |
| **Console** | The map, the scenarios, and the scoreboard — where the method gets checked. |

## What it found

Two claims about New York, from the city's own published data, with no
simulation involved:

**The city lists heat relief that does not work.** 100 of 1,026 sites are not
operational by NYC's own `status` field — 57 broken, 29 under construction, 10
not yet activated, 5 unknown. Buffering listed sites and working sites
separately puts **570,867 residents** across 162 tracts inside relief that
exists on paper and not in fact. Seven of the twelve worst tracts have nothing
working at all: Sunset Park (Central) reads 100% covered and has none.

**The blind spots are not evenly distributed.** 371,137 residents live in tracts
that cannot be called either way. **59.2%** of them are in the most vulnerable
fifth of the city, against 24.5% citywide — **2.42×**.

The two meet in the briefing: 93 of the 98 uncertifiable tracts resolve on the
same action — confirm the cooling centre is open and reachable — and the audit
is why that check is not a formality.

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

`make snapshot` is optional — a snapshot is committed, so a fresh clone runs
offline from `make setup && make build && make demo`.

### Deploying it

```bash
uv run nullsignal export       # bakes every API response to web/public/api
cd web && npm run build:static # emits web/dist, no backend required
```

`nullsignal export` walks the same code paths the live API does and writes the
result as files, so the published site cannot drift from what the engine
computes. Pushing to `main` runs both steps in CI and publishes to GitHub Pages
(`.github/workflows/pages.yml`); `VITE_BASE` sets the subpath.

### Generated explanations

Without credentials the prose is written deterministically from the evidence
packet — no network, no model, and a demo that cannot break. With a key set,
the same packet is sent to Claude and the output is checked against the packet's
numbers before it is shown:

```bash
export ANTHROPIC_API_KEY=...
uv run nullsignal export       # prints how many were generated vs templated
```

The model never sees a risk score or a decision state either way; see
[Explanation](#explanation).

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
| baseline | **83.9%** | 5,030,204 | 6.9% | 0h |
| NullSignal | **0.0%** | 0 | 0.0% | **2h** |

> **54.5%** of the residents the conventional dashboard kept calling safe are in
> the most vulnerable quintile, against **40.2%** citywide — **1.36x**.

The two hours are the point: NullSignal stops confirming safety when the feed
freezes, not when the harm arrives. It knows it has gone blind before there is
anything to see.

The baseline is not asleep through this. At t+9h, when service actually stops
and residents call 311, it correctly escalates from 229 alerting tracts to 749.
Then reporting collapses in exactly those tracts, and it falls to 6 alerting,
then to **zero by t+13h** — declaring the whole city clear at the worst hour of
the day. It did not fail to notice the emergency. It noticed, and then read the
disappearance of the evidence as the emergency ending.

### Across twelve scenarios

| Scenario | Baseline FR / FA | NullSignal FR / FA | |
| --- | --- | --- | --- |
| compound failure (three at once) | 92.9% / 6.4% | **0.0% / 0.0%** | win |
| heatwave, silent transit failure | 83.9% / 6.9% | **0.0% / 0.0%** | win |
| honest outage | 37.1% / 8.2% | **0.0% / 0.0%** | win |
| all-clear (control, nothing wrong) | 0.0% / 9.8% | **0.0% / 0.0%** | win |
| sensor drift, one station | 4.2% / 65.0% \* | **2.8% / 5.1%** | win |
| delayed transit feed | 0.0% / 62.4% \* | **0.0% / 0.0%** | \* |
| flatlined feed | 0.0% / 57.3% \* | **0.0% / 0.0%** | \* |
| partial sensor coverage | 0.0% / 64.2% \* | **0.0% / 0.0%** | \* |
| slow burn (no fault at all) | 0.0% / 50.6% \* | 3.1% / 4.7% | \* |
| reporting collapse | 0.0% / 60.4% \* | 5.3% / 12.8% | \* |
| contradicting transit feed | 0.0% / 64.2% \* | 92.3% / 4.7% | \* |
| sensor drift, every station | 37.1% / 16.7% | 92.3% / 0.0% | **beaten** |

\* Stopped clocks — a 0% false-reassurance rate bought by claiming danger 50–65%
of the time. The tool flags these rather than letting the comparison stand.

Counted honestly: **five clear wins**, including `all-clear` (a calm city, no
fault) and `sensor-drift-single-station`, where NullSignal is better on *both*
columns at once. Six are stopped clocks, where the baseline's zero is not worth
having. **One is a straight loss, and it is the interesting one.**

### The loss

`sensor-drift-masking-heat` moves every thermometer in the city together and
gradually, so the reading stays plausible through most of the harm window. It
defeats every liveness detector by construction — the payload changes, the clock
advances, each individual reading is defensible — and with one weather source
per borough there is no second source of the same kind to disagree with it. A
**sole witness lying well**. NullSignal falsely reassures on 92.3% of endangered tracts; the
baseline, on 37.1%.

`contradicting-transit-feed` is the same shape: a feed that changes its payload,
advances its clock, and reports the opposite of the truth. The baseline's 0%
there is a stopped clock (64.2% false alarm), so it is not a loss on the
scoreboard — but NullSignal is still fooled, and that is worth saying plainly.

Every failure with a second opinion available is caught — a frozen feed, a stale
feed, a partial feed, one drifting station, three faults at once. What is not
caught is a sole witness lying well.

**Both losses reduce to one root cause, and it is measurable.** Detecting a
lying source means finding something that disagrees with it, and this system
carries one source per subject: one transit feed, one weather provider. A
direct conflict needs two claims about the *same* proposition, so on live data
it fires on **zero** tracts. There is never a second witness to call the first
one wrong.

Two softer rules do fire, comparing a hazard reading against how much residents
are actually calling: dangerous heat with the tract gone quiet, and its mirror,
residents calling well above their own rate with no instrument accounting for
it. The second one *does* catch the drift — from t+7h the affected tracts carry
`nws says heat_exposure=low but 311 says population_distress=elevated`, and on
live data it names 359 tracts where something is going on that no instrument
explains. It shows in the tract panel. It is still not enough to change the
verdict:
conflict carries 20% of the sufficiency weight against a 0.55 threshold, so
even total disagreement lands at 0.80. Contradiction contributes to a decision;
it never makes one. A test asserts that limit rather than leaving it to be
rediscovered.

Raising that weight would flip both scenarios, which is exactly why it was not
done on a deadline. On live data 359 tracts (15.4%) already carry an
unexplained-distress conflict, because people call 311 about a great many
things that are not heat. Making conflict decisive would turn all of them
`UNKNOWN` on a calm day, and an engine that cannot stay quiet has learned the
wrong lesson. The real fix is a second source of the same kind — the seven MTA
subway feeds read as independent claims, a second weather provider — so that
disagreement is between two instruments rather than between an instrument and a
proxy. **It is not built.** The scenarios stay in the suite and tests assert
the limits, so its absence cannot be mistaken for a fix.

### Two different failures, two different columns

An earlier version folded UNKNOWN into the false-alarm rate, and the canonical
scenario read 33% "false alarms". Almost all of them were a still-frozen
transit feed after the heat had eased, where declining to certify safety was
exactly right.

Saying "we cannot confirm this is safe" asserts nothing about danger. It is the
behaviour this system exists to produce, and counting it as crying wolf made
honesty look like noise. Separated, NullSignal claims danger falsely **0.0%**
of the time on the canonical scenario; the baseline does so 6.9% of the time
and structurally cannot report an unresolved case at all.

Six of the baseline's figures are stopped clocks — its 0% false reassurance on
reporting collapse is bought by alarming 60.4% of the time — and the tool flags
those rather than letting the comparison stand.

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

## Heat relief

The harm mechanism in the scenario is "no way to reach a cooling centre", so the
cooling network is modelled from NYC Parks' Cool It! data — 1,026 misting
stations and spray showers.

Coverage is computed **twice**: once over every listed site, once over only the
ones that work. `status` marks 57 broken, 28 under construction and 10 never
activated, so a system counting listed sites overstates available relief — and
does so invisibly, because a broken misting station looks like a working one in
any dataset that does not read the field.

| | |
| --- | --- |
| Tracts with no working relief within 500m | **269** |
| Tracts listed as covered that are not | **36** (114,526 residents) |
| Overstatement, least vulnerable quintile | 0.010 |
| Overstatement, most vulnerable quintile | **0.037** |

Broken relief is concentrated where it matters most: the overstatement is 3.7x
larger in the most vulnerable fifth of the city than the least.

> One trap worth recording: the two source datasets come from the same agency
> and use the same column names, `x` and `y`, in **different coordinate
> systems** — cooling sites in lon/lat, spray showers in NY State Plane feet.
> Nothing in either schema says so. Reading both the same way places 755 sites
> in the Gulf of Guinea. The system is classified per row by magnitude rather
> than assumed per dataset.

## Climatology — the reference no fault can move

Cross-station agreement compares instruments to each other, so a fault that
moves *every* station the same way passes it unremarked. That case was a
documented loss until the system gained an outside reference: ten years of
day-of-year normals for New York, from Open-Meteo's keyless archive.

A citywide reading far from what a decade of the same date has actually done is
anomalous however well the stations agree with one another. Uniform drift went
from **96.6% false reassurance to 70.5%** — from losing to the baseline to
beating it.

Two things keep it from firing on ordinary weather. The threshold comes from
the observed spread rather than being chosen — NYC daily maxima vary about
7.7°F around their normal, so a two-sigma day is merely notable. And the bounds
are asymmetric: a heat index legitimately runs well above the air temperature
these normals are built from, so the upper bound is generous, while the lower
one is not — reading cool is the direction a drifting sensor fails in and the
direction that gets people hurt. A genuine 108°F heatwave passes; a 20°F drift
does not.

## Air quality

NYC Community Air Survey, by community district, crosswalked to tracts through
`cdta2020`. Ozone earns its place in a heat system because ozone formation is
temperature-driven: hot days are bad-air days, and the same residents absorb both.

**It is annual data, and that governs how it may be used.** A 2024 mean is not
evidence about this afternoon. It shapes the *prior* on how often a hot day here
is a genuine emergency, and never the likelihood of any observation — a test
asserts the words `ozone`, `pm25` and `air_burden` do not appear anywhere in the
likelihood layer.

Another honest negative: across NYC, ozone is essentially **flat by
vulnerability quintile** (32.9 to 33.5 ppb), as is PM2.5. It is a compound
hazard, not an equity signal, and it is used as one.

## Verified from a clean clone

The offline claim is tested, not asserted. A fresh clone with no network:

```
git clone … && uv venv && uv pip install -e ".[dev]"
uv run nullsignal build     # 4.5s, 155 files, 28MB, committed data only
uv run pytest               # 170 passed
uv run nullsignal eval      # identical to the working directory
```

The scoreboard is anchored to when the snapshot was taken, not to when the
evaluation runs. Without that it drifted as the fixtures aged — 311 freshness
decays against wall clock, so the unresolved rate crept by more than three
points at a week and four at a month. A number that changes depending on the calendar is
an anecdote, so it is now a property of the scenario and the snapshot alone.

This caught a real bug that a working directory hides. The weather join
filtered on wall-clock `now()`, so a committed snapshot silently stopped
matching a day after it was taken — weather became a missing critical source
and **every tract in the city fell to UNKNOWN**. The engine's behaviour was
correct throughout; it declined to certify safety without weather. But the gap
was self-inflicted, and it was invisible locally because a working directory
keeps getting refreshed. The window is now anchored to the snapshot's own
forecast, as the 311 window already was, with a regression test that fails if
any source silently stops joining.

## Demoing it

`docs/DEMO.md` — a ninety-second runbook, rehearsed against the production
build, including the questions it draws and what to say when it loses.

## Status

Complete: 7 of 7 days. See `docs/PLAN.md`.

The suite doubles as a build progress meter: invariants for components not yet
built are skipped with the day they unlock, rather than quietly passing.

```
make test
```
