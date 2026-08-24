# NullSignal — Build Plan

**Target:** 7-day hackathon build · NYC · Python engine + React UI
**Thesis:** Absence of evidence is not evidence of absence. Make that computable.

---

## 1. Context

Public-safety monitoring systems share a silent defect: they encode *no data* as *no problem*.
A neighborhood that stopped reporting and a neighborhood with nothing to report render the
same shade of green. When a feed dies quietly — HTTP 200, timestamp frozen — the dashboard
stays calm.

This produces **algorithmic exclusion**: communities that report less get watched less, not
because they are safer but because they are dimmer to the system.

NullSignal's contribution is one architectural move: **make "we don't know" a first-class
state that "low risk" can never collapse into**, then prove the difference is measurable.

---

## 2. The core idea, precisely

### The 2×2 — not a 1-D ramp

Risk and evidence-sufficiency are **orthogonal axes**. Every existing dashboard projects them
onto a single green→red gradient, which is exactly where the harm hides.

|                    | Sufficiency LOW            | Sufficiency HIGH        |
| ------------------ | -------------------------- | ----------------------- |
| **Risk estimate LOW**  | ⬛ `UNKNOWN`               | 🟩 `CONFIRMED LOW`      |
| **Risk estimate HIGH** | 🟧 `SUSPECTED`             | 🟥 `CONFIRMED HIGH`     |

The two left-hand cells are unrepresentable in a conventional system. They are the product.

**Hard invariant:** `CONFIRMED LOW` requires low risk **AND** high sufficiency.
Silence can never produce green. This is one `if` statement and it is the entire thesis.

### Visual encoding follows the math

Risk → **hue**. Sufficiency → **texture**. Never merge the channels.
Low-sufficiency zones render with animated diagonal hatching / signal-noise grain, so a
"we're blind here" zone is *visually* distinct from a calm one at a glance. This is the
literal meaning of the name, and it keeps the map from looking like every other choropleth.

---

## 3. Engine architecture

Seven deterministic/probabilistic stages. The LLM touches only the last one.

```
sources → reliability → claims → contradiction graph → Bayesian posterior
                ↓                                            ↓
          bias correction                            sufficiency score
                                                             ↓
                                              decision state + VOI ranking
                                                             ↓
                                                  LLM explanation (verified)
```

### 3.1 Reliability & silent-failure detection

Per source `s`, zone `z`, time `t`:

- `freshness = exp(-Δt / τ_s)` where `τ_s` is the feed's *declared* cadence.
  A 30-second GTFS-RT feed 20 minutes stale scores ~0.
- `coverage(s,z)` = observable fraction of zone (sensors present / expected, stops served, area ∩).
- `liveness` = **the silent-failure detector**. A feed can be technically up and semantically dead.
  Three independent detectors:
  - **content-hash flatline** — payload byte-identical across N consecutive polls
  - **value flatline** — sensor reports a plausible constant (stuck ADC)
  - **cadence violation** — `Δt` exceeds `k·τ_s` while HTTP still returns 200
- `accuracy(s)` = rolling Brier score against ground truth where available.

`reliability = freshness · coverage · liveness · accuracy` ∈ [0,1]

### 3.2 Reporting-bias correction — the ethical core

311 report counts ≠ incident counts:

```
expected_reports(z) = incidents(z) × propensity(z)
```

`propensity(z)` is a latent per-zone reporting rate. Fit it by regressing observed report
rates on **CDC SVI** covariates (socioeconomic, household composition, minority/language,
housing/transport themes — all tract-level, already published, no invented weights).

Calibrate on complaint categories that have an independent verification channel
(e.g. 311 heat complaints vs. DOHMH heat-illness records), then:

```
incidents_hat(z) = reports(z) / propensity(z)      # with inflated CI where propensity is poorly identified
```

This is what converts "low reports ≠ low risk" from a slogan into a number.
Using the government's own vulnerability index rather than hand-tuned weights is what makes
it defensible to a skeptical judge.

### 3.3 Contradiction graph

Nodes = typed claims: `transit_service(z,t) ∈ {normal, degraded, halted}`,
`heat_exposure`, `power`, `cooling_center_reachable`.
Edges = `SUPPORTS` / `CONTRADICTS` / `IMPLIES`, weighted by source reliability.

**Contradiction mass** = `Σ min(rel_a, rel_b)` over contradicting pairs.
Two *reliable* sources disagreeing is a strong signal; two junk sources disagreeing is noise.

> **Do not fuse contradictions.** A Kalman filter or weighted mean would blend
> "transit halted" + "transit normal" into "mildly degraded" — laundering a crisis into a
> shrug. Contradictions must **widen the posterior**, not move its center.

### 3.4 Bayesian hypothesis update

Small discrete hypothesis space per zone (~6, exact inference, no sampling):

| | Hypothesis |
|---|---|
| H1 | Normal operations, genuinely low risk |
| H2 | Heat stress rising, transit nominal |
| H3 | Transit halted + heat rising → stranded-population risk |
| **H4** | **Feed/sensor silent failure masking H3** |
| **H5** | **Reporting suppression — real incidents, low reports** |
| H6 | Localized infrastructure fault (power / water) |

**H4 and H5 are the architectural innovation.** A conventional system has no hypothesis for
"my data is lying," so it can never conclude that it might be blind. Including them in the
space is what makes epistemic humility a computable outcome rather than a UI disclaimer.

**Reliability-discounted likelihoods** — the key trick:

```
P(e_obs | H) = rel · P(e | H) + (1 − rel) · P_uninformative(e)
```

As `rel → 0` the likelihood goes flat, so an unreliable observation *cannot move the
posterior*. Missing data doesn't push toward "safe" — it simply doesn't push, and the prior
(which carries SVI vulnerability) dominates. The math does the right thing by construction.

### 3.5 Sufficiency score

Deliberately **separate from risk**:

- normalized posterior entropy over hypotheses
- `evidence_coverage` = `Σ reliability_actual / Σ reliability_ideal`
- contradiction mass
- worst-case staleness among decision-critical sources

### 3.6 Value of Information — expected harm avoided

For each candidate verification action `a` (call transit ops, dispatch inspector, query
alternate API, check camera, resident callback):

```
VOI(a) = E_outcome[ max_d U(d | posterior after a) ] − max_d U(d | posterior now)
U = P(harm) × population_at_risk × vulnerability_multiplier − cost(a)
priority = VOI(a,z) / cost(a)
```

Hypothesis space ~6, action space ~8 → **exact EVPI by brute-force enumeration.**
No approximation, fully explainable, runs in milliseconds.

The `vulnerability_multiplier` (from SVI) is where equity becomes **structural rather than
decorative**: verification effort is pulled toward zones that are both uncertain and fragile.

### 3.7 LLM layer — explanation only, never decision

Hard boundary: **the model never sees or produces a risk number or a decision state.**
It receives a structured evidence packet and renders prose.

Two-tier safety:
1. **Placeholder mode** for the headline verdict — LLM emits narrative skeleton with
   `{{field}}` slots; the app substitutes values. Hallucinated numbers become *structurally
   impossible*.
2. **Numeric verifier** for free prose — every numeric token in the output must appear in the
   input packet within rounding tolerance, else reject and retry.

Plus a **deterministic template fallback** so a dead API key can never break the demo.
Cache explanations by packet hash — replays are instant and free.

> Load the `claude-api` skill before writing this layer for current model IDs and params.
> Default recommendation: Claude Sonnet 5 with tool-use-forced structured output.

---

## 4. The scoreboard — what actually wins

Without this, NullSignal is a nice dashboard. With it, it's a result.

Run the **identical scenario** through two engines:
- **Baseline** — the threshold dashboard cities have today: `reports < k AND sensor < θ → GREEN`
- **NullSignal**

Ground truth is known because the scenario engine generated it.

| Metric | Why it matters |
| --- | --- |
| **False-reassurance rate** | % of zone-hours labeled safe while ground truth was dangerous — **the headline** |
| **Equity gap** | false-reassurance in low-propensity zones **minus** high-propensity zones |
| Silent-failure lead time | hours between failure injection and detection |
| False-alarm rate | must not regress — proves you didn't just make everything orange |
| Verification efficiency | harm avoided per dispatch vs. random / round-robin |

**The equity gap is the most persuasive number in the project.** A slide reading:

> Baseline falsely reassures **34%** of the time in low-reporting neighborhoods vs **6%** in
> high-reporting ones — a **28-point** equity gap.
> NullSignal: **8%** vs **7%** — a **1-point** gap.

…converts an ethics argument into a measured engineering result. Build toward this number.

### Failure injectors (scenario DSL)

```yaml
name: heatwave-transit-silent-failure
timeline:
  - {t: 0h,  weather.temp_c: 34}
  - {t: 6h,  weather.heat_index_c: 47}
  - {t: 7h,  inject: {source: gtfs_rt, mode: STALE_BUT_200}}
  - {t: 8h,  inject: {source: 311, mode: SUPPRESS, factor: 0.2}}
  - {t: 9h,  ground_truth: {transit_service: HALTED}}
```

Modes: `STALE_BUT_200` · `FLATLINE` · `DROPOUT` · `SLOW_DRIFT` · `SUPPRESS` ·
`CONTRADICT` · `LATENCY` · `PARTIAL_COVERAGE`

---

## 5. Stack

**Engine** — Python 3.14 + uv · FastAPI + Pydantic · numpy/scipy · **DuckDB** · h3-py
**UI** — Vite + React + TS · **MapLibre GL** (no token) + deck.gl · TanStack Query · Zustand
**Transport** — SSE for the tick stream (one-directional; simpler than WebSocket)

*DuckDB over Postgres:* no Docker on this machine, file-based, ships in the repo, spatial
extension available, and a judge can run the whole thing with one command.
*MapLibre over Mapbox:* no API token to leak, expire, or rate-limit mid-demo.

```
nullsignal/
├── engine/src/nullsignal/
│   ├── sources/      # one adapter per feed
│   ├── reliability/  # freshness · coverage · liveness · silent-failure detectors
│   ├── bias/         # SVI-based reporting-propensity model
│   ├── claims/       # claim extraction + contradiction graph
│   ├── inference/    # hypotheses + reliability-discounted Bayesian update
│   ├── sufficiency/  # sufficiency score + the 2×2 decision rule
│   ├── voi/          # exact EVPI
│   ├── explain/      # LLM + numeric verifier + template fallback
│   ├── sim/          # scenario engine + failure injectors
│   ├── eval/         # baseline engine + scoreboard
│   └── api/          # FastAPI + SSE
├── web/              # React
├── data/raw/         # committed snapshots — demo must run offline
└── scenarios/*.yaml
```

**Zone grid:** NYC 2020 census tracts (~2,325). Tract-level because CDC SVI is tract-level —
no spatial re-aggregation, no invented weights. deck.gl renders this count trivially.

---

## 6. Verified data sources

| Source | Auth | Verified |
| --- | --- | --- |
| NYC 311 `erm2-nwe9` | none | ✅ live, **99.2% geocoded** |
| MTA GTFS-RT | none | ✅ 200, ~103KB protobuf |
| NWS `api.weather.gov` | none | ✅ — **403 without contact email in `User-Agent`** |
| CDC SVI 2022 (NY tracts) | none | ✅ 3.9MB CSV |
| NYC Census Tracts 2020 `i82y-eyru` | none | ✅ in catalog |
| OpenAQ v3 | **free key** | ⚠️ 401 without |
| Cooling centers / heat mortality | none | ⚠️ in catalog, `/resource/` 404 — resolve Day 1 |

**Snapshot-first.** Pull once, commit to `data/raw/`, run offline. The demo must never depend
on conference wifi — and it makes the eval reproducible, which matters more.

> 311 is ~99% geocoded, so the missingness story is cleanly about **reporting propensity**,
> not geocoding gaps. Sharper thesis, and it survives a hostile question.

---

## 7. Seven days

**Walking-skeleton strategy:** Day 1 ships the *entire pipeline end-to-end with stub math*.
Every subsequent day replaces one stub with real math. There is never a day where nothing runs.

| Day | Deliverable |
| --- | --- |
| **1** | **Skeleton + real ingest.** Snapshot script → DuckDB → tracts+SVI join → stub inference → API → map renders 4 states. `make demo` works end-to-end. |
| **2** | **Reliability + silent-failure detection.** All three liveness detectors, real freshness/coverage. |
| **3** | **Bias model + contradiction graph.** SVI propensity regression; claim extraction; contradiction mass. |
| **4** | **Bayesian core + sufficiency + VOI.** Replaces the Day-1 stub. Exact EVPI. The 2×2 goes live. |
| **5** | **Scenario engine + baseline + scoreboard.** Injectors, ground-truth track, **the equity-gap number**. |
| **6** | **UI depth.** Evidence panel, VOI queue, time scrubber, side-by-side baseline toggle, hatching texture. |
| **7** | **LLM explanation + demo rehearsal + buffer.** |

Front-load a throwaway scoreboard on Day 1 (fake numbers, real plumbing) so the highest-risk
deliverable has six days of runway, not one.

---

## 8. Invariants as tests

These six pytest cases **are** the product spec. If they pass, NullSignal works.

```python
test_silence_never_confirms_safe()        # zero evidence → UNKNOWN, never CONFIRMED_LOW
test_contradiction_widens_not_averages()  # 2 reliable conflicting sources → entropy ↑, no midpoint
test_stale_source_cannot_move_posterior() # freshness→0 ⇒ KL(posterior‖prior)→0
test_equity_monotonicity()                # evidence fixed, SVI ↑ ⇒ VOI of verifying ↑
test_silent_failure_beats_baseline()      # lead time > 0 on canonical scenario
test_llm_emits_no_unsupported_numbers()   # every numeric token traces to the packet
```

---

## 9. Demo script (90 seconds)

1. **T+0** — Map calm. Baseline and NullSignal agree. Both mostly green.
2. **T+7h** — Inject `STALE_BUT_200` on GTFS-RT. *Baseline does not flinch* — HTTP 200, no alarm.
3. **T+8h** — Suppress 311 in three low-propensity tracts.
   **Baseline turns them greener** (fewer complaints = safer). This is the money shot.
4. **NullSignal flips them to ⬛ UNKNOWN** with signal-noise hatching, and says:
   > *"Not confirmed safe. Transit feed has not changed content in 68 minutes against a
   > 30-second cadence. 311 volume dropped 80% while heat index rose 6°C — inconsistent.
   > Highest-value next check: verify transit via alternate source (est. 4.2× harm reduction)."*
5. **T+9h** — Reveal ground truth: transit **was** halted. Baseline still green.
6. **Scoreboard.** Equity gap: 28 points → 1 point.

---

## 10. Risks

| Risk | Mitigation |
| --- | --- |
| Propensity model isn't identifiable from available data | Fall back to SVI-prior propensity with wide CIs; the pipeline is unchanged, only the tightness of the estimate |
| Scoreboard shows no improvement | Front-load to Day 1 (stub) / Day 5 (real) — six days to tune, not one |
| Over-flagging UNKNOWN makes map useless | False-alarm rate is a tracked metric; tune `θ_suff` against it |
| Judge dismisses it as "a dashboard" | Lead with the equity gap, not the map |
| Live API dies mid-demo | Snapshot-first; committed fixtures; zero network calls at demo time |

---

## 11. Verification

```bash
uv run pytest engine/tests -v          # the six invariants must pass
uv run nullsignal snapshot             # reproducible ingest → data/raw/
uv run nullsignal eval --scenario heatwave-transit-silent-failure
                                       # prints the scoreboard table
make demo                              # engine + web, offline, deterministic replay
```

End-to-end acceptance: `eval` prints a **non-trivial equity-gap reduction** and
`test_silent_failure_beats_baseline` reports **lead time > 0**.
