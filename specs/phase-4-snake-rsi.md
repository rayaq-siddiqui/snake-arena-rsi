# Phase 4 — Snakes That Improve Themselves

**Goal:** connect each of the five personalities to the phase 3 framework so every snake
runs its own independent improvement lineage, tuning its own parameters generation after
generation — and prove, with held-out numbers, whether it actually got better.

## 1. Five lineages, one protocol

- Each personality is a separate **lineage** with its own champion, archive, proposer
  state and improvement log. A lineage can only change **its own** params file
  (`arena/agents/params/<name>.json`) within the bounds its `ParamSpace` declares.
- All five use the *same* proposer type, acceptance rule and budget, so differences in
  progress come from the personalities, not from unequal treatment.
- Code, engine rules, features, evaluator, seeds and acceptance rule are **frozen** for
  the whole run. A test checks that a run changes nothing outside `runs/` and the
  version-stamped params files it writes there.

## 2. A generation

A generation gives each of the five snakes one improvement attempt, **sequentially in a
fixed order** (Hunter, Survivor, Trapper, Predictor, Opportunist) for reproducibility:

1. **Freeze** all five current champions as they stand at the start of the generation.
   Snake *i*'s attempt is evaluated against these frozen versions, so the order inside a
   generation doesn't give anyone an advantage.
2. For each snake, run one phase 3 step: propose → validate → dev screen → holdout →
   decide → archive.
3. After all five decisions, commit the new champions together and write the generation
   record.

## 3. The snake evaluator

Implements the phase 3 `Evaluator` for one lineage.

**Evaluation episode:** a fixed-length game of `eval_ticks` (default **5,000**) with the
win target disabled, so every episode is the same length and kill *rates* are
comparable. (The first-to-100 rule still governs normal matches and the viewer.)

**Score (primary):** the snake's credited kills per 1,000 ticks in that episode.

**Pairing:** for each seed, play two episodes with *identical* opponents, seats and
spawn RNG — one with the candidate, one with the champion. The per-seed difference is
the paired sample. Because spawns are seeded identically, the two games diverge only
because of the snake's own choices.

**Opponent mixtures:** each seed draws a mixture (deterministically from the seed):

| Share | Opponents in the other four seats |
|---|---|
| 50% | the other four lineages' current (frozen) champions |
| 25% | random members of the other lineages' halls of fame, including generation 0 |
| 15% | the fixed **reference portfolio**: the five hand-set phase 2 personalities |
| 10% | `RandomSafe` snakes |

**Seat rotation:** the candidate's seat (spawn order) cycles through all five seats
across seeds.

**Guard metrics** (from phase 3's guard rule):

- deaths per 1,000 alive ticks may not rise by more than **15%**;
- self + wall deaths may not rise by more than **25%** (catches reckless "kamikaze"
  aggression that trades lives for kills);
- zero crashes or decision-budget violations.

## 4. Default run configuration

```yaml
generations: 10
proposer: GaussianHillClimb       # sigma starts at 0.15 in normalised space
dev_pairs: 100                    # per candidate
holdout_pairs: 100                # per candidate, one extension of 100 allowed
min_rel_gain: 0.02
bootstrap_resamples: 10000
eval_ticks: 5000
patience: 4                       # per lineage; a stalled lineage stops proposing
workers: auto                     # process pool; results independent of worker count
```

Plus a `--quick` profile (40 × 40 board, 1,000-tick episodes, 20 + 20 pairs) used by
tests and for a fast end-to-end demo. Quick results are labelled as such and never
reported as the real experiment.

**Compute estimate:** one candidate costs up to `2 × (100 + 200)` = 600 episodes of
5,000 ticks = 3,000,000 ticks. Five snakes ⇒ 15M ticks per generation. At the phase 1
target (20k ticks/s per process) that's ~12.5 minutes per generation on one core, and
proportionally less with a process pool. Measure and record the real figure.

## 5. Reporting

`python -m arena.cli report runs/<run-id>` writes `report.md` and PNG charts:

- **Progress chart:** per snake, kills per 1,000 ticks of each generation's champion,
  measured on the untouched **final** seeds against the **reference portfolio**, with
  95% bootstrap bands.
- **Fixed vs evolved:** each evolved champion vs its own generation-0 self on final
  seeds — the headline "did it improve?" number, with its interval.
- **Hall-of-fame check:** each final champion vs *all* earlier champions of every
  lineage, to catch cycles (A beats B beats C beats A).
- **5 × 5 kill matrix** of the final champions.
- **Decision log:** every proposal with what changed, dev and holdout numbers, the
  interval, guard metrics, and accept/reject with reason.
- **Behaviour drift:** the phase 2 behaviour metrics per generation (did the Survivor
  learn to hunt?).

## 6. Watching evolved snakes

```bash
python -m arena.cli evolve --generations 3 [--quick] --run-id demo
python -m arena.cli report runs/demo
python -m arena.cli watch --run runs/demo --generation 3 --seed 7
python -m arena.cli watch --run runs/demo --vs-generation 0   # evolved vs original
```

The viewer shows each snake's lineage version (for example `Hunter v4`) and can load any
archived champion, so every historical version stays watchable.

## 7. Acceptance criteria

- `evolve --generations 3` completes with no human input, for both the default and the
  `--quick` profile.
- Re-running the same run config (same run seed) gives byte-identical
  `generations.jsonl` decisions, regardless of worker count.
- Killing the process mid-generation and resuming gives the same final result as an
  uninterrupted run.
- A run modifies nothing outside its run directory; every archived champion is
  immutable and can be loaded and replayed after later generations.
- The proposer never receives holdout or final seeds (spy test).
- A deliberately broken candidate (params out of bounds, or a policy patched to raise)
  is never promoted.
- The report is generated and its numbers match the stored generation records.
- **Honest outcome:** the report states whether each lineage improved on final seeds
  versus its generation-0 self, with the interval. "No significant improvement" is a
  valid, reportable result; it is never hidden or re-run until it looks better.

## As built

Where the code differs from the text above, the code is the reference:

- **Modules.** `arena/evolution/entrants.py` (a policy with its parameters and version),
  `evaluator.py`, `run.py` (profiles, lineages, the lockstep `Evolution`), `report.py`
  and `watch.py`. There is no separate `lineage.py`; a `Lineage` is a small dataclass in
  `run.py` around one phase 3 `Run`.
- **Where params live.** A run never writes `arena/agents/params/`. Each accepted
  champion is written to `runs/<id>/params/<name>/v<k>.json` (v1 is the hand-set start)
  and the latest to `runs/<id>/params/<name>.json`. The repository-hash test checks that a
  run changes nothing outside its run directory.
- **Joint commit and resume.** Each lineage commits its own record, but generation *g*
  is evaluated against champions read from the lineage records at *g − 1*, so the five
  attempts in a generation see the same frozen opponents. A process killed between two
  lineage commits resumes by skipping lineages already at *g*, which replays the same
  decisions (tested).
- **No move budget in evaluation.** The phase 2 decision budget is wall-clock time, which
  would make decisions depend on machine load. Evaluation episodes run without it;
  "failures" are seeds where the candidate needed engine fallbacks (a crash or an
  invalid action), and any failure blocks promotion.
- **Score.** Kills × 1,000 / episode ticks, with the win target disabled. Guards use the
  phase 3 guard rule with the tolerances above plus a small absolute slack (0.05) so a
  zero baseline doesn't make every increase infinite.
- **Profiles.** `default` is the configuration in section 4. Two reduced profiles exist,
  and every report from them is labelled as not the specified experiment:
  - `quick`: 40 × 40, 1,000-tick episodes, 20 + 20 pairs, 40 final pairs.
  - `experiment`: 24 × 24, 2,000-tick episodes, 40 + 40 pairs, 100 final pairs. The
    personalities are cautious, so on larger boards almost every paired seed scores zero
    kills for both sides (on 40 × 40, 1,000 ticks: 0–5 of 40 seeds had any kill; on
    24 × 24, 2,000 ticks: 1–12 of 40), and the default profile costs hours per
    generation on one machine. These figures are in `specs/plan.md`, Measurements.
- **Charts.** `report` writes `report.md`, `report.json` and one SVG small-multiples
  chart (`progress.svg`) rather than PNGs, so the report needs no plotting dependency.
- **Hall-of-fame check.** Each final champion plays every earlier version of its own
  lineage on the final seeds with all four other seats drawn from every lineage's hall
  of fame, so all earlier champions of every lineage appear as opponents.
- **Watching.** `watch --run` exposes every archived version as a policy (`hunter@v4`,
  shown as "Hunter v4"). `--vs-generation K` seats a lineage's current and generation-K
  versions in one six-seat game with the other four current champions.
- **The arena profile, harness and cup (plan step 5.8).** `--profile arena` trains every
  lineage on the cup's own game (30 × 30, 10-cell snakes, 2,000-tick episodes) with the
  `score` objective: kills minus the self-death penalty per wall or own-body death, per
  1,000 ticks, the points that win matches. Each lineage's proposer is an
  `AdaptiveHarness` seeded with its personality's strategy prior (which parameters to
  try first), so each snake tunes its own search from its dev games. The acceptance rule
  and holdout are unchanged. After every generation the champions and a `random_safe`
  snake play the arena cup (`cup.jsonl`); `--until-wins N` stops the run when one snake
  has N cup wins. The cup only measures: no decision reads it, and its seeds are derived
  from their own purpose tag.
