# Phase 5 — The big arena: ten snakes, four new personalities and a learner

The owner's next experiment: take everything the first four phases learned to a much
larger game. The board grows to **1000 × 1000**, snakes grow to **20 cells**, and **ten
snakes** play: the five existing personalities, **four new ones** and the random snake.
One new snake, the **Learner**, does not start from hand-set weights. It learns from the
other snakes' experience, closer to reinforcement learning than to the hand-tuned
personalities. Then every lineage, the Learner included, runs the improvement loop on the
big board, and we watch how the Learner does.

Every rule in [phase 1](phase-1-arena.md) through [phase 4](phase-4-snake-rsi.md) still
holds, unless this spec changes it explicitly. That includes one engine, determinism,
the improver never grading itself, and holdout seeds hidden from whatever proposes changes.

## 1. Engine limits

The engine validates its config. Raise these limits; the defaults stay the same:

| Setting | Was | Now |
|---|---|---|
| Board side | 10..500 | 10..1000 |
| Snakes | 1..8 | 1..10 |
| Snake length | 3..10 | 3..20 |

The rules don't change. Spawning must still place every snake on a 1000 × 1000 board,
and the fuzz tests must cover the new limits: 10 snakes of length 20 on a small board,
where spawn falls back to its scan.

## 2. Four new personalities

Each new personality is a `ScoringPolicy` with a bounded `ParamSpace`, a
`params/<name>.json` and a strategy brief, the same as the first five. Each one fills a
role that none of the first five plays.

| Name | Idea | New features it needs |
|---|---|---|
| **Scavenger** | Goes where fights are. It heads for the closest pair of enemies that are near each other, waits at the edge and finishes snakes that have run out of room. | `fight_distance`: distance from the new head to the midpoint of the closest enemy pair within `fight_radius`, normalised |
| **Herder** | Pushes enemies toward walls and corners. It positions itself between the nearest enemy and the board centre, so the enemy's free space shrinks against the wall. | `enemy_wall_distance`: the nearest enemy's distance to its nearest wall after my move, normalised |
| **Ambusher** | Patrols slowly near the busiest region and turns across an enemy's path only when the cut is certain. It does not chase. | `crossing_ahead`: 1 if the new head sits on a cell some enemy reaches within `ambush_depth` moves on its current heading, and I reach it first |
| **Learner** | Has no hand-set weights. A linear move scorer over **every** feature in `FEATURES`, with weights fitted from the other snakes' experience (§3). | none |

New features go into `arena/agents/features.py` with golden tests, like the existing
ones. Distance features are normalised so that they stay informative on a 1000-cell
board. Any change to an existing feature's scale must leave behaviour on boards up to
100 × 100 unchanged, and tests must show that.

The Phase 2 acceptance check (`check-personalities`) extends to the new names. Each new
personality must:
- beat `random_safe` on kills;
- show its role in the behaviour metrics, where a metric fits:
  - the Scavenger is near fights more often;
  - the Herder's victims die nearer walls;
  - the Ambusher scores more kills per tick spent moving toward an enemy.

## 3. The Learner: learning from the other snakes

**Data.** Every training game logs, for **every** snake on the board, the feature vector
of each legal move at each tick and the move it took. It also logs what followed within a
horizon of `H` ticks:
- `+1` for each kill credited to that snake;
- `−1` for its death;
- `−penalty` for a wall or own-body death.

The Learner therefore learns from moves it didn't make: the other nine snakes' decisions
and their results are its training data.

**Fit.** Fit a linear action-value model `Q(s, a) = w · f(s, a)` by ridge regression on
those discounted returns. This is fitted Q evaluation on logged experience, in NumPy, in
`arena/evolution/learner.py`. The fit outputs a weight vector in the Learner's
`ParamSpace`, clipped to its bounds. The policy itself stays stdlib-only: it loads weights
from its params file and scores moves with them, like every other personality.

**How the fit enters the loop.** It enters as a **proposer**: `LearnerProposer` proposes
the freshly fitted weights as a candidate. It may also propose a mix of the fit and the
current champion. The candidate then goes through the usual dev screen, holdout test,
acceptance rule and guards. Fitting never bypasses acceptance.

Data comes **only from dev games** and from the cup games already played. It never comes
from holdout or final seeds. The improver still changes only the Learner's own
parameters.

**Generation 0.** The first fit uses logs from a fixed batch of dev-seed games among the
nine other snakes. The Learner starts from that fit, not from zeros, and it is recorded as
version 1.

## 4. The big experiment

**Board and lineup.** 1000 × 1000 board, 10 snakes of length 20. Seats, in order:
Hunter, Survivor, Trapper, Predictor, Opportunist, Scavenger, Herder, Ambusher, Learner,
`random_safe`.

**Profile.** A new `evolve --profile big`. Every lineage except the random snake runs the
`AdaptiveHarness`. The Learner's harness also has `LearnerProposer` as an extra operator.
Episode length and pair counts are set from the measurements in §5, so that a
generation fits in about 3 hours on 4 workers. The profile is labelled as reduced wherever
it differs from the phase 4 default.

**Cup.** As in step 5.8: after every generation, the champions play cup matches, and wins add up
in `cup.jsonl`. A big-cup match is 20,000 ticks, and the most points wins (§5).

**Coach.** The opt-in `HarnessCoach` may be used, under the same budget rules: numbers
only, clipped, audit-logged, dev feedback only. Total LLM spend stays capped by
`--max-coach-dollars`.

**What we report.**
- The Learner's cup wins and score per 1,000 ticks against each generation of itself
  (generation 0 fit vs final).
- The same against each other personality.
- Which features its learned weights favour, compared with the hand-set personalities.
- Accepts, final-seed CIs and cup standings for all nine lineages.

No claim that the Learner improved without a final-seed CI that excludes zero.

## 5. Measured so far, and what it means for the profile

These numbers come from the five existing personalities, each played twice, with 10
snakes of length 20 on a 1000 × 1000 board, on one core, seed 1:

| Ticks | Time | Kills on the whole board |
|---|---|---|
| 2,000 | 21.1 s | 0 |
| 20,000 | 233.9 s (about 85 ticks/s) | 4 (four snakes with 1 each) |

That is about **0.2 kills per 1,000 ticks for the whole board**, and about 0.02 per snake.
This has three consequences:

- **No win target.** A first-to-10 cup match would almost never finish. A big-cup match
  instead plays a fixed 20,000 ticks, about 4 minutes, and the snake with the most points
  wins. A tie means no winner.
- **The score signal is sparse.** Kills alone give almost no signal per episode. The
  `big` profile's objective therefore adds a dense, role-neutral term: time spent within
  `engage_radius` of an enemy head, at a small weight. Kills still dominate, and this is
  reported separately from kills.
- **Compute is the limit.** Paired evaluation of 9 lineages on 10,000-tick episodes at
  85 ticks/s costs about 2 minutes per game. Step 6.2 therefore speeds the engine and
  features up on big boards before the run. Until then, the profile is set so that one
  generation takes **at most about 3 hours on 4 workers**: fewer pairs and a smaller
  batch, labelled as reduced.

## 6. Viewer

The viewer and replay browser show 10 snakes with 10 distinct colours. Each colour pair
must pass the dataviz palette validator, and each snake also gets a name label, so colour
is never the only cue. A 1000 × 1000 board renders scaled to fit, with a zoom that follows
a chosen snake.
