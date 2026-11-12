# 2. Worked Examples

Every idea the build uses, shown with small numbers you can check with a calculator.
These examples double as the **structure we build from**: each one names the module in
`specs/plan.md` that implements it.

---

## Example A — Hill climbing one knob

*Implements:* `GaussianHillClimb` (phase 3).

The Survivor snake has a knob called `w_wall_distance`: how much it likes staying away
from walls. Right now it's **3.0**. Higher means more wall-shy.

| Round | Try | Old score | New score | Keep? | Knob afterwards |
|---|---|---|---|---|---|
| 1 | 3.0 → 3.6 | 1.10 | 1.25 | ✅ better | 3.6 |
| 2 | 3.6 → 4.3 | 1.25 | 1.31 | ✅ better | 4.3 |
| 3 | 4.3 → 5.1 | 1.31 | 1.18 | ❌ worse | 4.3 |
| 4 | 4.3 → 3.9 | 1.31 | 1.27 | ❌ worse | 4.3 |

*(scores = kills per 1,000 ticks, averaged over many games)*

This is **hill climbing**: take a small step, keep it if it goes uphill. Picture walking
up a hill in fog — you can only feel the slope under your feet. It's simple and it works,
but it can get stuck on a small hill (a *local optimum*) when a taller one exists
elsewhere. That's why we also run `RandomRestart` (jump somewhere random) as a control,
and `CrossEntropy` (search with a whole cloud of guesses).

---

## Example B — Why we compare on the same games ("pairing")

*Implements:* the paired evaluator (phases 3–4).

We test a new Hunter (candidate) against the current Hunter (champion) on 10 starting
setups ("seeds"). Same seed = same spawn spots, same opponents.

| Seed | Champion | Candidate | Difference |
|---|---|---|---|
| 1 | 2.0 | 2.4 | +0.4 |
| 2 | 0.6 | 0.8 | +0.2 |
| 3 | 3.4 | 3.6 | +0.2 |
| 4 | 1.2 | 1.6 | +0.4 |
| 5 | 2.8 | 2.8 | 0.0 |
| 6 | 0.4 | 0.8 | +0.4 |
| 7 | 1.8 | 2.0 | +0.2 |
| 8 | 3.0 | 3.4 | +0.4 |
| 9 | 1.0 | 1.2 | +0.2 |
| 10 | 2.2 | 2.6 | +0.4 |
| **Average** | **1.84** | **2.12** | **+0.28** |

Look at the champion column: scores swing from 0.4 to 3.4 depending on the seed. Some
seeds are just harder (you spawn in a corner, enemies spawn far away). That swing is
**noise** and it's huge compared with the +0.28 we care about.

Now look at the *difference* column: it barely moves (0.0 to 0.4). Comparing on the same
seed cancels the "hard seed / easy seed" luck. Measured with a bootstrap (Example C), the
95% range for the improvement is:

- **Unpaired** (pretend the games were unrelated): about **−0.58 to +1.12** — can't tell if
  it's better at all.
- **Paired** (compare seed by seed): about **+0.20 to +0.36** — clearly better.

Same data, same games. Pairing turns "no idea" into "confident."

---

## Example C — The bootstrap: how sure are we?

*Implements:* `PairedBootstrapRule` (phase 3).

We have 10 differences. We want to know: if we ran *other* random seeds, could the
average difference come out ≤ 0?

The bootstrap's trick: **pretend our 10 numbers are the whole world, and re-draw from
them.**

1. Write the 10 differences on 10 slips of paper. Put them in a hat.
2. Draw a slip, write it down, **put it back**. Do this 10 times. Average them.
   - e.g. draw `+0.4, +0.2, +0.2, 0.0, +0.4, +0.4, +0.2, +0.2, +0.4, 0.0` → average **+0.24**
3. Repeat step 2 ten thousand times (a computer does this in a blink).
4. Sort the 10,000 averages. The middle 95% (from the 250th to the 9,750th) is the
   **95% confidence interval**.

For our data that's about **+0.20 to +0.36**. The whole range is above zero, so we
**accept**. If the range had been −0.05 to +0.40, we'd **reject** (or test more) even
though the average looks good — because "maybe it's no better at all" is still on the
table.

Our acceptance rule also requires the gain to be at least **+2%** of the champion's score,
so we don't promote changes that are real but too tiny to matter.

---

## Example D — Lucky winners (why we need a holdout)

*Implements:* dev / holdout / final seed pools (phase 3).

Suppose all 20 ideas we try are **useless** — they don't change anything. We test each on
5 games and keep anything that "wins" by a lot. With only 5 noisy games each, a couple of
those 20 will look like big winners just by chance. If we keep them, we've learned
nothing — we just picked the luckiest coins.

Fix: **two exams.**

- **Dev seeds (practice exam):** cheap first screen. The proposer is allowed to see these
  results.
- **Holdout seeds (real exam):** fresh games the proposer has never seen. A candidate only
  wins if it passes here too.
- **Final seeds (report card):** untouched until the end, used only to report results.

A lucky winner on dev usually falls back to average on holdout — which is exactly how we
catch it. Phase 3 has a test for this: feed the loop 200 useless candidates and check it
accepts almost none.

---

## Example E — The 1/5th success rule (improving the improver)

*Implements:* self-adapting step size in `GaussianHillClimb` (phase 3).

How big a step should hill climbing take?

- Steps too **big**: you keep overshooting; almost everything is rejected.
- Steps too **small**: almost everything "works" but you crawl.

A classic rule from evolution strategies (Rechenberg, 1973): **aim for about 1 in 5
proposals being accepted.**

Our version: step size `σ` × **1.5** after an accept, × **0.9** after a reject.

| Event | σ |
|---|---|
| start | 0.150 |
| reject | 0.135 |
| reject | 0.122 |
| accept | 0.182 |
| reject | 0.164 |

Why 1.5 and 0.9? The size is stable when `1.5^p × 0.9^(1−p) = 1`, which happens when the
accept rate `p ≈ 0.21` — about 1 in 5. Accepting more often than that grows the steps;
less often shrinks them. The improver is tuning **itself** from its own track record —
a small, safe slice of "improving the improver."

---

## Example F — Rock, paper, scissors (why we keep a hall of fame)

*Implements:* the archive and opponent mixtures (phases 3–4).

Imagine three versions of the Trapper:

- **v1** plays "rock" (charges straight at enemies).
- **v2** learned to beat v1: "paper" (sidesteps and traps chargers).
- **v3** learned to beat v2: "scissors" (ignores trappers and hunts the open board)…
  but v1's charging beats v3.

If each version is only tested against the *current* rivals, the lineage can go around
in circles forever while every single step "improves." That's **cycling**.

Fix: keep every accepted version in an immutable **hall of fame**, and make 25% of
evaluation games use opponents drawn from it, plus a fixed *reference portfolio* (the
original hand-made snakes). A real improvement must beat the past as well as the present.
The final report checks each champion against **all** earlier champions to catch cycles.

---

## Example G — The kamikaze snake (reward hacking)

*Implements:* guard metrics (phase 4).

The official score counts kills and **ignores deaths**. Suppose the Hunter's search
finds this "improvement": charge every enemy at full speed and don't bother dodging.

| Version | Kills / 1,000 ticks | Deaths / 1,000 alive ticks |
|---|---|---|
| Champion | 1.9 | 4.0 |
| Kamikaze | 2.0 | 9.5 |

Kills went up 5%, so by the score alone it passes. But it more than doubled its deaths —
it's winning by throwing its life away, which also hands free respawn-time to everyone
else. This is **reward hacking**: doing great on the number while missing the point.

Fix: **guard metrics** that a candidate must not break even if its score improves —
deaths may not rise more than 15%, wall/self deaths not more than 25%. The kamikaze is
rejected with the reason written in the log.

---

## Example H — The judge you can't bribe

*Implements:* frozen evaluator and isolation tests (phases 3–4).

A student allowed to edit both their essay *and* the answer key will always get 100%.
That's not learning.

In Snake Arena the improver can change **only one snake's own params file**. It cannot
touch the engine, the scoring, the evaluator, the seeds, the tests or the acceptance
rule. Tests check this after every run. An optional LLM proposer may suggest **numbers
only**, within bounds — never code — so its output can't do anything sneaky.

---

## Example I — Co-evolution: the arms race

*Implements:* frozen-champion generations (phase 4).

Generation 1: Hunter gets better at chasing. Generation 2: Survivor, now facing a better
Hunter, gets better at escaping. Generation 3: Hunter, facing a better Survivor, learns
to cut off escape routes. Each lineage's improvement changes the problem the others are
solving.

This is the "recursive" engine of the whole project: **today's winner is tomorrow's
opponent.** It's also why we freeze all five champions at the start of each generation —
so the order snakes take their turns in doesn't hand anyone an unfair advantage.
