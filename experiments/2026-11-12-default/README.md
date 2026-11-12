# 2026-11-12 default: the specified experiment, 3 generations

**Result: one of five lineages improved.** Trapper accepted one change in generation 3,
and on the final seeds, which no decision saw, its evolved champion beats its
generation-0 self. The other four lineages accepted nothing and are unchanged.

This used the **default profile** from `specs/phase-4-snake-rsi.md`: 100 × 100 board,
5,000-tick episodes, 100 dev + 100 holdout pairs, 200 final pairs,
`gaussian_hill_climb`, min gain 2%, patience 4, run seed 0. The run was capped at 3
generations (the acceptance run) rather than the specified 10.

- **View it:** open [`dashboard.html`](dashboard.html) in a browser, or read
  [`report.md`](report.md) (chart: [`progress.svg`](progress.svg)).
- **Reproduce:** `uv run python -m arena.cli evolve --generations 3 --run-id
  2026-11-12-default --workers 4`, then `uv run python -m arena.cli report
  runs/2026-11-12-default --workers 4`. The decisions do not depend on the worker count.
  Passing a larger `--generations` resumes the same run.
- **Watch it:** `uv run python -m arena.cli watch --run experiments/2026-11-12-default
  --vs-generation 0` seats Trapper v2 and Trapper v1 in one game.
- **Code:** commit 3cfed63, `arena/rsi` code hash `c1faa27590837b50`.

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
| Proposals | 3 | 3 | 3 | 3 | 3 |
| Reached holdout | 0 | 1 | 2 | 1 | 2 |
| Accepted | 0 | 0 | 1 | 0 | 0 |

Two other proposals had positive holdout gains, but their intervals reached zero:
Predictor gen 1 (+7.3%) and Trapper gen 2 (+22.9%). Opportunist's generation 1 candidate
had a large gain (+375%, CI [+0.012, +0.05]), but it was rejected by the self + wall
death guard: the guard working as designed.

Kills stay rare on the full board: the final champions scored 20 kills in 200
five-snake episodes of 5,000 ticks.

## Cost

On a 4-core cloud container with 4 workers:

- Generations 1-3: 2,885, 3,224 and 2,132 s (1,600, 1,800 and 1,200 episodes, about
  7 s per episode per worker). 8,934 s in total.
- The report took about 58 minutes.
