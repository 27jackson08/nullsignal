# NullSignal — demo runbook

Ninety seconds, three acts. Every number is reproducible from the committed
snapshot; nothing is staged.

The order follows the product rather than the build history: what it gives you,
why that is not a formality, and how we know where to look. The scoreboard —
the strongest-looking number here — comes last on purpose, because it is the
only part measured against an adversary this repository wrote.

## Before you start

Open **<https://27jackson08.github.io/nullsignal/>**. Nothing needs to be
running and nothing touches the network. To present locally instead:

```bash
make demo        # engine on :8000, map on :5173
```

The two are the same build against the same snapshot.

> The link opens on the briefing. A welcome card appears once per browser over
> the **map**, so if you plan to show the console, open it and dismiss the card
> before you record.

---

## Act 1 — What it gives you (30s)

You land on the work order.

> "This is what a duty officer gets at the start of a heat shift. Not a risk
> map — a list of places to send people."

Point at the three figures.

> "Ninety-eight tracts in New York can't be called either way tonight. Three
> hundred and seventy thousand people live in them. And they aren't spread
> evenly: **59% of those residents are in the most vulnerable fifth of the
> city, against 24% citywide.** Where the system goes blind, it goes blind
> about the people who can least afford it."

Scroll to the assignments.

> "Eight assignments, ranked by the people behind each unresolved call — not by
> risk. A tract we understand needs no visit however bad it is. Each one says
> what's blocking the call and gives one action with a time on it. It prints,
> because the point of an order is that it leaves the screen."

Point at the second column of the first row, then click **Came back clear**.

> "And when the crew reports back, the doubt actually resolves. Sufficiency
> goes from 0.40 to 0.66, the tract becomes callable, and six thousand people
> stop standing in a blind spot — not because anything changed on the ground,
> but because somebody went and looked. That's the whole argument in one
> click."

If someone asks what happens when it's bad news, click **Found a problem** on
another row.

> "Then it leaves this list entirely. It's no longer a question of evidence —
> it belongs in a response plan."

---

## Act 2 — Why that check is not a formality (25s)

Scroll back to **Why we ask you to confirm rather than assume**.

> "Eighty-seven of those ninety-eight tracts settle on the same three-minute
> action. And notice the note underneath each one: confirming the cooling
> centre is *also* worth doing — it wouldn't settle the call, but it's what
> would most change the response."

Click **Read the audit**.

> "Here's why we don't let anyone skip it. New York publishes 1,026 heat-relief
> sites with an operational status field. **A hundred of them are not working**
> — and that's the city's own word, not our judgement. Fifty-seven broken,
> twenty-eight under construction, ten not yet activated."

Scroll to the coverage bars.

> "Buffer the listed sites, buffer only the working ones, and the difference is
> 570,000 residents living inside relief that exists on paper and not in fact.
> Seven of these twelve have nothing working at all. **Sunset Park reads a
> hundred percent covered and has none.**"

Let that sit.

> "Every map of cooling centres in this city plots the locations and drops the
> status. A broken spray shower becomes a dot that looks exactly like a working
> one. That's the whole thesis, in concrete: the absence of relief rendered as
> its presence."

---

## Act 3 — How we know where to look (35s)

Switch to **Console**.

> "Every census tract in New York on live public data. Green means we checked
> and it's fine. **Hatched means we can't tell** — and we never colour that
> green. Printed maps have hatched uncertain ground for two centuries; that's
> all this is."

Scenario picker → **heatwave-transit-silent-failure**. Scrub to **t+7h**:

> *"transit feed freezes, still answering 200 with normal service"*

The map goes heavily hatched — **1,228 tracts**.

> "The feed is still returning HTTP 200, correct content type, a hundred
> kilobytes of plausible protobuf saying service is normal. Nothing is down."

Switch to **Baseline**: unchanged at **229 alerting**.

Scrub to **t+9h** — the baseline **escalates to 749**.

> "And give it credit: it works. Service stopped, people called 311, the
> dashboard caught the surge. This is not a straw man."

Now **t+10h** — it falls to **6**. Keep going to **t+13h**: **zero**.

> "Nothing got better. The heat is still there, the trains are still stopped,
> the people are still stranded. What changed is that they stopped calling —
> and the dashboard read the silence as the emergency resolving. It escalated
> correctly, then stood all the way down to all-clear at the worst hour of the
> day."

Switch back to **NullSignal** at the same tick: **1,486 unknown**.

> "We go the other way. Less certain, not more."

Open **Result**.

| | False reassurance | Residents | Warning |
| --- | --- | --- | --- |
| Conventional dashboard | **83.9%** | 5,030,204 | 0h |
| NullSignal | **0.0%** | 0 | **2h** |

> "Of the tracts where people were genuinely in danger, that dashboard called
> 84% of them safe. We called none of them safe, and we reacted two hours
> before the harm — when the feed froze, not when people got hurt."

---

## If you have another 30 seconds

Say the part most demos leave out.

> "Three things I want to be straight about. The check ranking was wrong until
> recently: we ranked verification by value of information, which scores how
> much a result changes the *response*. For a tract nobody can call that's the
> wrong question — the highest-value check was a twenty-minute errand that
> couldn't lift the ceiling, and the checks that could scored exactly zero. A
> project claiming risk and evidence are orthogonal was ranking on one axis.
> It's fixed, and it's in the README, because finding that in your own system
> is the point.
>
> Second, that 84% is measured against a
> baseline I wrote, in a scenario I wrote — it shows the method works, it isn't
> proof about the world. The audit is. And we tried to check the equity claim
> against real outcomes, using EMS heat dispatches the engine never reads.
> **It came back empty** — 286 dispatches citywide across 59 districts, about
> five each, and five events can't separate one district from another. It's in
> the README. A project about not confusing silence with safety doesn't get to
> drop the check that didn't work out."

Then the scenario it loses:

> "One of the twelve scenarios beats us outright, and the tool prints that it
> was beaten. When every weather station drifts the same way there's nothing
> left to disagree with. A single drifting station we do catch. The scenario
> stays in the suite and a test asserts the limit, so nobody mistakes its
> absence for a fix."

---

## Questions you will get

**"Isn't this just crying wolf?"**
No — and the scoreboard keeps the two apart on purpose. On the canonical
scenario NullSignal's false-alarm rate is **0.0%**: it never once claimed danger
where nothing was wrong. What it does do is decline to certify safety 25.9% of
the time, which is a different act and is reported in its own column rather than
folded into the same number. Six of the twelve scenarios also show the
*baseline* scoring zero false reassurance purely by alarming 50–64% of the time,
and the tool flags those as stopped clocks rather than claiming a win.

**"Does the AI decide anything?"**
No. The language model never sees a risk score or a decision state, and it
cannot write a number — it emits `{{field}}` placeholders the application
substitutes. Fabrication is structurally impossible, not merely caught. Every
verdict comes from an exactly-enumerated posterior over eight hypotheses. With
no API key configured the prose is written deterministically from the same
evidence packet, which is the default and the guaranteed floor.

**"Isn't the cooling-centre finding just stale data?"**
Possibly, and the audit says so in its own words: it does not claim the status
field is current, that anyone was harmed, or that any site is unattended. It
claims the city publishes both facts and that most maps carry only one.

**"Where does the vulnerability weighting come from?"**
CDC's published Social Vulnerability Index, at tract level. Nothing hand-tuned.

**"Would this work in my city?"**
The engine is city-agnostic; the adapters are NYC-specific. Any city with 311,
a GTFS-realtime feed, and census geography needs new adapters, not new logic.

---

## Failure modes during the demo

| Symptom | Cause | Fix |
| --- | --- | --- |
| Briefing or audit won't load | store missing | `make build` |
| "Engine unreachable" | API not running | `uv run nullsignal serve` |
| Welcome card in your first frame | first visit in this browser | open the console once and dismiss it |
| Printed order stops partway | stale build | the shell unwinds for paper since 2026-08-29; rebuild |
| Scenario slow on first scrub | simulation not cached | run `nullsignal eval` first |
| Explanation reads flatly | no `ANTHROPIC_API_KEY` | expected; the template is the floor |

Nothing here needs network access. Every source is a committed snapshot.
