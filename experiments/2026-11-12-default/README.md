# 2026-11-12 default: the specified experiment

**Result: one of five lineages improved.** Trapper accepted one change in generation 3,
and on the final seeds, which no decision saw, its evolved champion beats its
generation-0 self. The other four lineages accepted nothing and are unchanged. The run
was given the specified 10 generations and stopped on its own after generation 7: every
lineage had gone 4 generations without an accept (patience 4).

This used the **default profile** from `specs/phase-4-snake-rsi.md`: 100 × 100 board,
5,000-tick episodes, 100 dev + 100 holdout pairs, 200 final pairs,
`gaussian_hill_climb`, min gain 2%, patience 4, run seed 0, 10 generations. It first
ran as the 3-generation acceptance run (that snapshot is in git history at commit
1bb372e), then was resumed with `--generations 10`. The container restarted twice during
the resumed part; each time the run resumed from its last committed generation, which
gives the same decisions as an uninterrupted run (tested).

- **View it:** open [`dashboard.html`](dashboard.html) in a browser, or read
  [`report.md`](report.md) (chart: [`progress.svg`](progress.svg)).
- **Reproduce:** `uv run python -m arena.cli evolve --generations 10 --run-id
  2026-11-12-default --workers 4`, then `uv run python -m arena.cli report
  runs/2026-11-12-default --workers 4`. The decisions do not depend on the worker count.
  Passing a larger `--generations` resumes the same run.
- **Watch it:** `uv run python -m arena.cli watch --run experiments/2026-11-12-default
  --vs-generation 0` seats Trapper v2 and Trapper v1 in one game.
- **Code:** generations 1-3 ran at commit 3cfed63 (`arena/rsi` code hash
  `c1faa27590837b50`), generations 4-7 at commit 996ab05. In between, only `arena/cli.py`,
  `arena/evolution/run.py` and `arena/rsi/store.py` changed (run provenance and budget
  flags), not the engine, policies, evaluator or acceptance rule.
- **Report games:** the report's games depend only on each lineage's champions and final
  seeds, which did not change after generation 3, so the games played for the
  3-generation report were kept. The decision log, counts and stop reason were
  recomputed from the generation records. Run `report --rebuild` to play them again.

## The one accepted change

Trapper, generation 3: `keep_distance 3 -> 2`, `w_space 6 -> 4.897`, so it keeps closer
to rivals and weights open space a little less.

| | dev (100 pairs) | holdout (100 pairs) | final seeds (200 pairs) |
|---|---|---|---|
| Kills / 1k ticks, candidate vs champion | 0.100 vs 0.048 | 0.144 vs 0.072 | 0.128 vs 0.075 |
| Paired difference (95% CI) | +0.052 | +0.072 [+0.026, +0.130] | +0.053 [+0.024, +0.087] |
| Deaths / 1k alive ticks, candidate vs champion | | 0.008 vs 0.016 | |
| Self + wall deaths, candidate vs champion | | 0.03 vs 0.05 | |

It earned its kills without dying more. Against the four hand-set personalities alone,
Trapper's kill rate rose from 0.001 to 0.005 per 1,000 ticks, and the hall-of-fame check
(v2 vs v1, opponents from every hall) is +0.004 [+0.000, +0.009]: no sign of a cycle.

The 24 × 24 baseline (`../2026-11-12-baseline/`) proposed the same change for Trapper in
its generation 3. There it was rejected: holdout +0.0%, 95% CI [-0.10, +0.10]. With 100
holdout pairs on the full board, the gain was clear.

## Everything else

| | Hunter | Survivor | Trapper | Predictor | Opportunist |
|---|---|---|---|---|---|
| Proposals | 4 | 4 | 7 | 4 | 4 |
| Reached holdout | 0 | 1 | 3 | 1 | 3 |
| Accepted | 0 | 0 | 1 | 0 | 0 |

Two other proposals had positive holdout gains, but their intervals reached zero:
Predictor gen 1 (+7.3%) and Trapper gen 2 (+22.9%). Opportunist's generation 1 candidate
had a large gain (+375%, CI [+0.012, +0.05]), but it was rejected by the self + wall
death guard: the guard working as designed.

Generations 4-7 found nothing: the two proposals that reached holdout (Trapper and
Opportunist in generation 4) had gains of +0.0%, and Trapper's generations 5-7 all lost
on dev seeds.

Kills stay rare on the full board: the final champions scored 20 kills in 200
five-snake episodes of 5,000 ticks.

## Cost

On a 4-core cloud container with 4 workers:

- Generations 1-3: 2,885, 3,224 and 2,132 s (1,600, 1,800 and 1,200 episodes, about
  7 s per episode per worker).
- Generation 4: 2,701 s (1,400 episodes). Generations 5-7, Trapper only: 338, 393 and
  373 s (200 episodes each).
- 12,046 s (3.3 h) for all 7 generations.
- The report took about 58 minutes.
