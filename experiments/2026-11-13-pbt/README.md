# 2026-11-13 PBT-style population vs the hill climber (plan step 5.3)

**Result: a tie.** `PopulationHillClimb` (`--proposer pbt`, 4 members, the worst one
copies a top one each generation) did as well as the default `GaussianHillClimb`, within
noise, on every setting tried. The hill climber stays the default.

- **Setup:** for each of 40 seeds, one `NoisyQuadratic` toy problem and one `Run` per
  proposer, 50 dev and 50 holdout pairs, paired bootstrap acceptance. Every proposer gets
  the same **episode** budget, so the population, which screens 4 candidates a
  generation, runs fewer generations. Score: the true score of the final champion
  (0 is the optimum, higher is better). Differences are paired by problem; the 95% CI is
  a bootstrap over the 40 problems.
- **Reproduce:** `uv run python experiments/2026-11-13-pbt/compare.py --workers 4`
  (add `--episodes 3000` or `--dim 10` for the other rows; under 30 s each on 4 cores).

| Problem | Episodes | Hill climb | pbt | pbt − hill climb [95% CI] | cross_entropy − hill climb | random_restart − hill climb |
|---|---|---|---|---|---|---|
| 5-D | 12,000 | −0.757 | −0.703 | +0.054 [−0.218, +0.381] | −2.573 [−3.775, −1.536] | −6.270 [−7.394, −5.191] |
| 5-D | 3,000 | −6.971 | −7.272 | −0.301 [−2.254, +1.608] | −2.823 [−5.547, −0.441] | −5.555 [−7.661, −3.628] |
| 10-D | 12,000 | −6.122 | −6.223 | −0.101 [−2.634, +3.175] | −4.216 [−7.202, −0.634] | −30.144 [−34.273, −25.674] |

Raw scores per seed are in `results.json` (5-D, 12,000), `results-3000.json` and
`results-dim10.json`.

Why a tie is plausible: on a smooth quadratic a single adaptive hill climber already
makes steady progress, and spending four times the dev games per generation buys
robustness to bad steps rather than speed. PBT is built for problems where a member can
get stuck; whether the snakes are such a problem is an open question, and
`evolve --proposer pbt` lets it be measured on them.
