# NullSignal — demo runbook

Ninety seconds, five moves. Every number below is reproducible from the
committed snapshot; nothing is staged.

Rehearsed against the production build on 2026-08-26. The baseline is a
working dashboard, not a prop: at t+9h it correctly escalates from 229 alerting
tracts to 749 when service actually stops. Then 311 reporting collapses, and by
t+13h it is alerting on **zero** — it stands down to all-clear at the moment the
emergency peaks. Say that out loud; it is the strongest thing in the demo.

## Before you start

Either open the deployed build —
**<https://27jackson08.github.io/nullsignal/>** — which needs nothing running,
or serve it locally:

```bash
make demo        # engine on :8000, map on :5173
```

The two are the same build against the same snapshot. Use the local one if the
venue's network is unreliable; use the deployed one if you would rather not
have a terminal on screen.

Wait for the map to render (2,325 tracts, ~2s). Leave the browser on
**NullSignal** view, live data. Have a second terminal ready.

> If the room is small, run `uv run nullsignal eval` once beforehand so the
> scenario is cached — the first request runs the simulation (~4s), later ones
> are instant.

---

## 1 — The claim, on live data (15s)

> "This is every census tract in New York, right now, on real public data.
> Green means we checked and it's fine. **Hatched means we don't know.**"

Point at the header: **124 of 2,325 tracts**.

> "A conventional dashboard calls all 124 of these safe. We won't — and not
> because we think they're dangerous. Because CDC suppressed the vulnerability
> data for some of them, and others have no subway we can observe. We don't
> know who lives there or how they'd leave."

Click any hatched tract. The panel names the missing source.

**Do not skip this.** It establishes that the hatching is real data, before any
simulation appears.

---

## 2 — Start the scenario (10s)

Scenario picker → **heatwave-transit-silent-failure**. Timeline appears.

> "Heat climbing into the low nineties. Below any advisory threshold — no city
> issues a warning at 94 degrees."

Scrub to **t+6h**. Map still mostly green.

---

## 3 — The failure nobody sees (20s)

Scrub to **t+7h**. Read the caption aloud:

> *"transit feed freezes, still answering 200 with normal service"*

The map goes heavily hatched — **1,228 tracts**.

> "The feed is still returning HTTP 200. Correct content type. A hundred
> kilobytes of plausible protobuf saying service is normal. Nothing is down."

Switch to **Baseline**. Nothing changes: **229 alerting, 2,096 called low**,
exactly as at t+0h.

> "That's the same moment on a conventional dashboard. It cannot see this,
> because there is nothing to see. Every threshold it monitors is satisfied."

Switch back to **NullSignal**.

---

## 4 — The harm arrives (20s)

Scrub to **t+9h**:

> *"service actually stops — invisible to anyone reading the frozen feed"*

Switch to **Ground truth**. Red appears across the transit-dependent tracts.

> "That's what was actually happening. People who depend on transit, in heat
> that's survivable only if you can leave it, with no way to reach a cooling
> centre."

Switch to **Baseline** once more. It has **escalated — 749 alerting**.

> "And give it credit: it works. Service stopped, people called 311, and the
> dashboard caught the surge. This is not a straw man."

Now scrub forward to **t+10h**:

> *"reporting collapses in the affected tracts"*

The baseline falls to **6 alerting**. Keep scrubbing to **t+13h**: **zero**.

> "Nothing got better. The heat is still there, the trains are still stopped,
> the people are still stranded. What changed is that they stopped calling —
> and the dashboard read the silence as the emergency resolving. It escalated
> correctly, then stood all the way down to all-clear at the worst moment of
> the day."

Switch back to **NullSignal** for the same tick: **1,486 unknown**, and rising.

> "We go the other way. Less certain, not more — because losing the evidence is
> a reason to doubt the all-clear, not to issue one."

---

## 5 — The number (25s)

Second terminal:

```bash
uv run nullsignal eval
```

| | False reassurance | Residents | Warning |
| --- | --- | --- | --- |
| Conventional dashboard | **83.9%** | 5,030,204 | 0h |
| NullSignal | **0.0%** | 0 | **2h** |

> "Of the tracts where people were genuinely in danger, the dashboard called
> 84% of them safe — five million residents. We called none of them safe. And
> we reacted two hours before the harm, when the feed froze, not when people
> got hurt."

Then the line that matters:

> "**54.5% of the residents that dashboard kept calling safe are in the most
> vulnerable fifth of the city — against 40.2% citywide.** It isn't that
> vulnerable neighbourhoods are less visible on average. It's that where the
> system goes blind, it goes blind about the people who can least afford it."

---

## If you have another 30 seconds

Run the scenario it loses:

```bash
uv run nullsignal eval --scenario sensor-drift-masking-heat
```

> "It prints that it was beaten. When every weather station drifts the same
> way, there's nothing left to disagree with — catching that needs a reference
> we don't have. A single drifting station we do catch. We left the scenario in
> the suite and wrote a test asserting the limit, so nobody mistakes its
> absence for a fix."

---

## Questions you will get

**"Isn't this just crying wolf?"**
No — and the scoreboard keeps the two apart on purpose. On the canonical
scenario NullSignal's false-alarm rate is **0.0%**: it never once claimed danger
where nothing was wrong. What it does do is decline to certify safety 25.9% of
the time, which is a different act and is reported in its own column rather than
folded into the same number. Three of the twelve scenarios also show the
*baseline* scoring zero false reassurance purely by alarming 50–64% of the time,
and the tool flags those as stopped clocks rather than claiming a win.

**"Does the AI decide anything?"**
No. The language model never sees a risk score or a decision state, and it
cannot write a number — it emits `{{field}}` placeholders the application
substitutes. Fabrication is structurally impossible, not merely caught. Every
verdict comes from an exactly-enumerated posterior over eight hypotheses.

**"Where does the vulnerability weighting come from?"**
CDC's published Social Vulnerability Index, at tract level. Nothing hand-tuned.

**"Would this work in my city?"**
The engine is city-agnostic; the adapters are NYC-specific. Any city with 311,
a GTFS-realtime feed, and census geography needs new adapters, not new logic.

---

## Failure modes during the demo

| Symptom | Cause | Fix |
| --- | --- | --- |
| Map blank | store missing | `make build` |
| "Engine unreachable" | API not running | `uv run nullsignal serve` |
| Scenario slow on first scrub | simulation not cached | run `nullsignal eval` first |
| Explanation reads flatly | no `ANTHROPIC_API_KEY` | expected; the template is the floor |

Nothing here needs network access. Every source is a committed snapshot.
