# 2026-11-13 Sequential acceptance and (1+1)-CMA-ES on the toy problems

**Result.**

- **`cma_es` is the stronger proposer.** It finished better than the default hill climber
  on all four problems, at the same episode budget. Every CI on the difference excludes 0.
- **The sequential rule reaches a good champion sooner.** `SequentialPairedRule` needed
  44–61% of the episodes the bootstrap rule needed to get there (median), with either
  proposer, on every smooth problem.
  It helps most on the 10-D ellipsoid, where it also gives the best final score. With
  `cma_es` on the two easy problems, though, it ends slightly but measurably worse than
  the bootstrap rule at the same budget (see below).
- **Fewer wrong accepts on pure noise.** The sequential rule wrongly accepted fewer
  candidates than the bootstrap rule, on both Gaussian noise and rare-event noise, and
  spent about a third fewer episodes doing it.
- **The defaults do not change.** `PairedBootstrapRule` and `gaussian_hill_climb` stay the
  defaults: the snakes' own evaluation has to confirm these gains first.

## Setup

- **Problems and runs.** Each of 20 seeds gets one toy problem. Each configuration
  (a proposer plus an acceptance rule) gets one `Run` per problem.
- **Budget.** Every configuration has the same **episode** budget, with 50 dev and
  50 holdout pairs.
- **Score.** The true score of the final champion. Higher is better.
- **Comparison.** Differences are taken against `gaussian_hill_climb+bootstrap`, paired by
  problem. The 95% CI is a bootstrap over the 20 problems.
- **Episodes to target.** The episodes used before the champion's regret first fell to
  10% of the starting regret. Regret is the optimum's true score minus the champion's.
  For the rare problem the target is 50%.
- **Accepts (not better).** The number of accepts, and in brackets how many accepted
  candidates were not truly better than the champion they replaced.

### Reproduce

Each command takes 1–3 minutes on 2 cores.

```bash
uv run python experiments/2026-11-13-rsi-upgrades/compare.py --workers 2 --problem quadratic
uv run python experiments/2026-11-13-rsi-upgrades/compare.py --workers 2 --problem ellipsoid
uv run python experiments/2026-11-13-rsi-upgrades/compare.py --workers 2 --problem ellipsoid --dim 10
uv run python experiments/2026-11-13-rsi-upgrades/compare.py --workers 2 --problem rare \
    --pairs 100 --episodes 24000 --target 0.5 \
    --configs gaussian_hill_climb+bootstrap,gaussian_hill_climb+sequential,cma_es+bootstrap,cma_es+sequential,random_restart+bootstrap
uv run python experiments/2026-11-13-rsi-upgrades/compare.py --workers 2 --seeds 10 --errors
```

### The problems

- **`quadratic`**: the existing `NoisyQuadratic`.
- **`ellipsoid`**: `NoisyEllipsoid`, a randomly rotated bowl with condition number 100. The
  best moves change several parameters together.
- **`rare`**: `RareEvents`, a Gaussian bump of expected counts with peak 1 and width 3.
  Each score is a Poisson draw, scaled by a gamma layout factor shared across the seed.
  Most of the space scores near 0, like kills in a short game. It gets 100 pairs and
  24,000 episodes because 50 pairs rarely resolve anything there.

## Results at equal episode budget

**Quadratic, 5-D, 12,000 episodes**

| Configuration | Mean score | vs default [95% CI] | Reached target | Median episodes to target | Generations | Accepts (not better) |
|---|---|---|---|---|---|---|
| hill climb + bootstrap (default) | −0.608 | — | 20/20 | 4,600 | 88 | 215 (1) |
| hill climb + sequential | −0.565 | +0.043 [−0.088, +0.180] | 20/20 | 2,225 | 143 | 228 (2) |
| cma_es + bootstrap | −0.309 | +0.299 [+0.134, +0.504] | 20/20 | 4,650 | 96 | 179 (0) |
| cma_es + sequential | −0.438 | +0.170 [−0.002, +0.372] | 20/20 | 2,065 | 156 | 175 (4) |
| random_restart + sequential | −4.605 | −3.997 [−5.027, −2.966] | 7/20 | 4,290 | 294 | 63 (0) |

**Ellipsoid, 5-D, 12,000 episodes**

| Configuration | Mean score | vs default [95% CI] | Reached target | Median episodes to target | Generations | Accepts (not better) |
|---|---|---|---|---|---|---|
| hill climb + bootstrap (default) | −1.820 | — | 12/20 | 1,700 | 83 | 149 (1) |
| hill climb + sequential | −1.618 | +0.202 [+0.021, +0.446] | 12/20 | 790 | 136 | 150 (0) |
| cma_es + bootstrap | −0.715 | +1.104 [+0.562, +1.670] | 18/20 | 3,650 | 94 | 147 (2) |
| cma_es + sequential | −0.869 | +0.951 [+0.396, +1.512] | 17/20 | 1,640 | 149 | 133 (2) |
| random_restart + sequential | −1.781 | +0.039 [−0.663, +0.769] | 10/20 | 2,080 | 291 | 76 (0) |

**Ellipsoid, 10-D, 12,000 episodes**

| Configuration | Mean score | vs default [95% CI] | Reached target | Median episodes to target | Generations | Accepts (not better) |
|---|---|---|---|---|---|---|
| hill climb + bootstrap (default) | −6.390 | — | 7/20 | 7,400 | 91 | 270 (1) |
| hill climb + sequential | −3.676 | +2.714 [+0.635, +6.280] | 11/20 | 4,490 | 147 | 311 (2) |
| cma_es + bootstrap | −3.293 | +3.096 [+0.493, +7.102] | 11/20 | 9,600 | 106 | 211 (0) |
| cma_es + sequential | **−2.351** | **+4.038 [+1.652, +8.008]** | **16/20** | 4,290 | 180 | 245 (3) |
| random_restart + sequential | −12.330 | −5.940 [−9.032, −1.381] | 1/20 | 10,810 | 294 | 64 (0) |

**Rare events, 5-D, 24,000 episodes, 100 pairs (peak score 1.0)**

| Configuration | Mean score | vs default [95% CI] | Reached 50% target | Median episodes to target | Generations | Accepts (not better) |
|---|---|---|---|---|---|---|
| hill climb + bootstrap (default) | 0.345 | — | 1/20 | 4,400 | 73 | 33 (7) |
| hill climb + sequential | 0.355 | +0.010 [−0.039, +0.074] | 1/20 | 5,150 | 129 | 26 (4) |
| cma_es + bootstrap | 0.666 | +0.321 [+0.203, +0.421] | 15/20 | 6,400 | 79 | 45 (1) |
| cma_es + sequential | 0.634 | +0.289 [+0.161, +0.407] | 15/20 | 3,050 | 142 | 47 (3) |
| random_restart + bootstrap | 0.687 | +0.342 [+0.239, +0.448] | 11/20 | 4,400 | 115 | 31 (0) |

Two notes on the rare-event rows:

- **The hill climber stalls here.** It changes one or two parameters at a time, and on
  the flat, near-zero part of the bump almost every step is rejected. Its 1/5th rule then
  shrinks the step size to the minimum, so it stops moving.
- **cma_es and random restarts keep going.** Both move every parameter at once, so a
  single step can reach the part of the bump where counts start to differ.

## False accepts on pure noise

Every candidate here has the same true score, so every accept is a false accept. The
setup is 10 seeds × 200 generations of hill climbing, 50 pairs, and holdout blocks
rotated every 10 generations (`--errors`).

| Noise | Rule | Accepts / generations | Accepts / holdout tests | Episodes |
|---|---|---|---|---|
| Gaussian (`PureNoise`) | bootstrap (default) | 33 / 2,000 (1.65%) | 33 / 970 (3.4%) | 307,600 |
| Gaussian | sequential | 19 / 2,000 (0.95%) | 19 / 711 (2.7%) | 205,590 |
| Gaussian | sequential, `min_pairs=10` | 15 / 2,000 (0.75%) | 15 / 615 (2.4%) | 174,914 |
| Rare events (`RareEvents(flat=True, peak=0.3)`) | bootstrap (default) | 30 / 2,000 (1.50%) | 30 / 897 (3.3%) | 322,500 |
| Rare events | sequential | 12 / 2,000 (0.60%) | 12 / 702 (1.7%) | 225,480 |
| Rare events | sequential, `min_pairs=10` | 11 / 2,000 (0.55%) | 11 / 627 (1.8%) | 196,652 |

**Reading the "per holdout test" rates.** Each holdout test is a one-sided test at a
nominal 2.5%. The standard error of a rate measured over about 700 tests is about 0.6
points, so:

- The sequential rule's 2.7% (Gaussian) and 1.7% (rare) are consistent with its 2.5%
  design.
- The bootstrap rule's 3.4% and 3.3% sit about 1.5 standard errors above 2.5%. That
  matches the known anti-conservatism of a percentile bootstrap CI followed by a
  data-dependent extension.

The sequential rule also sends fewer candidates to holdout in the first place (711
holdout tests against 970 on Gaussian noise), because dev racing can stop a candidate
after 20 or 25 of its 50 dev pairs.

## What was chosen and why

- **`min_pairs` defaults to 20.** An earlier 10-problem run tried 10 instead: it was a
  little faster on the quadratic (median 1,720 against 2,200 episodes to target), with no
  measurable change in final score. On rare-event counts, though, a first look at 10–12
  pairs is often all zeros, or a single event. The z statistic of such a sample is
  unreliable, so the default stays at 20.
- **Variants that did not help.** These were tried on 10 problems (5-D quadratic) and gave
  no measurable gain over the defaults:
  - a more lenient futility bound (`futility_z=-0.5`): 1,776 episodes to target;
  - a stricter one (`futility_z=0.5`): 1,720 episodes;
  - no dev early pass (`dev_pass_z=None`): 2,220 episodes, slower.

  They remain available as rule arguments.
- **Final score versus speed.** Here the sequential rule is compared with the bootstrap
  rule for the same proposer, paired by problem:

  | Problem | hill climb: sequential − bootstrap | cma_es: sequential − bootstrap |
  |---|---|---|
  | Quadratic 5-D | +0.043 [−0.088, +0.180] | −0.130 [−0.221, −0.045] |
  | Ellipsoid 5-D | +0.202 [+0.021, +0.446] | −0.153 [−0.280, −0.033] |
  | Ellipsoid 10-D | +2.714 [+0.635, +6.280] | +0.942 [+0.497, +1.473] |
  | Rare events 5-D | +0.010 [−0.039, +0.074] | −0.032 [−0.119, +0.047] |

  With `cma_es` on the two easy problems, the sequential rule ends measurably worse,
  even though it gets there sooner. The likely cause: near the optimum each gain is
  small, and a z test held at α = 2.5% needs more evidence to accept it than the
  bootstrap rule does (the bootstrap rule runs at about 3.4%). Fewer accepts also slow
  `cma_es`'s step-size and covariance updates. The sequential rule pays off most when
  the budget is tight or the problem is hard.

Raw per-problem numbers are in the `results-*.json` files next to this README.
