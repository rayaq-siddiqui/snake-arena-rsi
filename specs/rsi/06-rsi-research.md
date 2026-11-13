# 6. RSI Research: What the Literature Says and What We Changed

This chapter reviews the research behind the improvement loop. It covers what
"recursive self-improvement" means here, which families of methods fit the problem,
what was built because of them, and the measured effect of those changes on the toy
problems.

> **Rule for this chapter.** Every "better" below has a number next to it, measured on the
> toy problems at the same episode budget. The numbers come from
> `experiments/2026-11-13-rsi-upgrades/`.

---

## 1. What RSI is, and what it is not, in this project

**What it is.** Recursive self-improvement is a loop: a system proposes a change to
itself, checks whether the change helps, keeps it if it does, and the next round starts
from the improved version. The idea goes back to Good (1965). It becomes *recursive* when
the thing that improves includes the improver itself: the step size, which knobs to try,
eventually the search method.

**Snake Arena's version.** It is deliberately the **bounded** kind (chapter 3, "Where
research stood in 2026"):

- **The thing being improved** is a bounded vector of policy parameters. With an
  opt-in, review-only exception, it is a snake's own strategy file.
- **The judge is fixed.** The engine, the evaluator, the seed pools and the acceptance
  rule cannot be changed by the improver.
- **"Recursive" happens at two levels.** The proposers adapt their own settings from the
  accept history (σ, covariance, weights). `arena/rsi/meta.py` runs the loop on the
  hill climber's own settings.

**What it is not.**

- It does not modify a language model's weights.
- It does not rewrite its own acceptance rule.
- It does not claim unbounded or "explosive" growth.

The useful question here is narrower: **how many games does it take to find a better
policy, and how often does the loop fool itself?** The methods below are chosen by that
question.

**What makes the problem hard:**

1. **Noise.** One game says little. Kills are rare, mostly-zero counts.
2. **Cost.** Every comparison is two games' worth of CPU, so episodes are the budget.
3. **Adaptivity.** The loop runs hundreds of tests, each chosen after seeing earlier
   results. That is the setting in which ordinary p-values stop meaning what they say.
4. **Interacting knobs.** Weights trade off (more aggression needs less caution), so the
   good directions are often diagonal.

---

## 2. Families of approaches

Each family below gives the core idea, the key sources, and what it implies here.

### 2.1 Comparing two versions under noise: paired tests and common random numbers

**Idea.** Play old and new on the *same* seeds and compare the differences. This is the
"common random numbers" variance-reduction technique from simulation. It is why
`PairedResult` exists, and the toy problems show it working:

- the shared per-seed noise (sd 5) cancels;
- only the per-candidate noise (sd 1) remains.

**Sources.**

- P. Glasserman, D. D. Yao, "Some Guidelines and Guarantees for Common Random Numbers,"
  *Management Science* 38(6), 1992. [doi:10.1287/mnsc.38.6.884](https://doi.org/10.1287/mnsc.38.6.884)
- B. Efron, "Bootstrap Methods: Another Look at the Jackknife," *Annals of Statistics*,
  1979. [doi:10.1214/aos/1176344552](https://doi.org/10.1214/aos/1176344552)

**For us.** This was already built and stays. One finding is new. The existing
percentile-bootstrap rule, which runs an extension only when the CI straddles 0, accepted
pure noise in **3.4%** of holdout tests (33/970). Its nominal level is 2.5%, so the rule
is mildly anti-conservative. That sits about 1.5 standard errors above nominal, so it is
suggestive, not proven.

### 2.2 Sequential testing: stop as soon as the answer is clear

**Idea.** Don't fix the sample size in advance. Look at the data at planned points, and
stop as soon as it is clearly good or clearly bad.

- **Wald's SPRT** does this one observation at a time.
- **Group-sequential designs** look a few times and spend a fixed total error rate α
  across the looks. Clinical trials use them.
- **O'Brien-Fleming boundaries** are very strict early and close to the usual 1.96 at
  the end, so they cost almost nothing when the trial runs to completion.
- **Lan and DeMets's alpha-spending function** lets the look times be anywhere.

**Sources.**

- A. Wald, "Sequential Tests of Statistical Hypotheses," *Annals of Mathematical
  Statistics* 16(2), 1945. [doi:10.1214/aoms/1177731118](https://doi.org/10.1214/aoms/1177731118)
- S. J. Pocock, "Group sequential methods in the design and analysis of clinical
  trials," *Biometrika* 64(2), 1977. [doi:10.1093/biomet/64.2.191](https://doi.org/10.1093/biomet/64.2.191)
- P. C. O'Brien, T. R. Fleming, "A Multiple Testing Procedure for Clinical Trials,"
  *Biometrics* 35(3), 1979. [doi:10.2307/2530245](https://doi.org/10.2307/2530245)
- K. K. G. Lan, D. L. DeMets, "Discrete Sequential Boundaries for Clinical Trials,"
  *Biometrika* 70(3), 1983. [doi:10.1093/biomet/70.3.659](https://doi.org/10.1093/biomet/70.3.659)
- C. Jennison, B. W. Turnbull, *Group Sequential Methods with Applications to Clinical
  Trials*, Chapman & Hall/CRC, 2000.
- S. R. Howard, A. Ramdas, J. McAuliffe, J. Sekhon, "Time-uniform, nonparametric,
  nonasymptotic confidence sequences," *Annals of Statistics* 49(2), 2021.
  [arXiv:1810.08240](https://arxiv.org/abs/1810.08240). These are "anytime-valid"
  intervals that may be checked after every game.

**For us.** Most candidates are either clearly worse or clearly better long before 100
or 200 pairs. Built as `SequentialPairedRule` (§3.1).

### 2.3 Racing: drop losers early when screening many candidates

**Idea.** When several candidates compete, evaluate them a little at a time and drop any
candidate that is statistically behind. Racing does this; successive halving and
Hyperband do the same with fixed fractions.

**Sources.**

- O. Maron, A. W. Moore, "Hoeffding Races: Accelerating Model Selection Search for
  Classification and Function Approximation," *NeurIPS* 6, 1993.
  [proceedings](https://proceedings.neurips.cc/paper/1993/hash/02a32ad2669e6fe298e607fe7cc0e1a0-Abstract.html)
- M. Birattari, T. Stützle, L. Paquete, K. Varrentrapp, "A Racing Algorithm for
  Configuring Metaheuristics," *GECCO*, 2002. This is F-race.
- M. López-Ibáñez et al., "The irace package: Iterated racing for automatic algorithm
  configuration," *Operations Research Perspectives* 3, 2016.
  [doi:10.1016/j.orp.2016.09.002](https://doi.org/10.1016/j.orp.2016.09.002)
- V. Heidrich-Meisner, C. Igel, "Hoeffding and Bernstein Races for Selecting Policies in
  Evolutionary Direct Policy Search," *ICML*, 2009.
  [doi:10.1145/1553374.1553426](https://doi.org/10.1145/1553374.1553426). This one is
  closest to us: racing inside an evolution strategy that tunes policies.
- K. Jamieson, A. Talwalkar, "Non-stochastic Best Arm Identification and Hyperparameter
  Optimization," *AISTATS*, 2016. [arXiv:1502.07943](https://arxiv.org/abs/1502.07943)
- L. Li et al., "Hyperband: A Novel Bandit-Based Approach to Hyperparameter
  Optimization," *JMLR* 18, 2018. [arXiv:1603.06560](https://arxiv.org/abs/1603.06560)

**For us.** Dev screening is the right place for racing. Dev results never decide
acceptance, so stopping early there cannot add false accepts. Built into
`SequentialPairedRule`'s dev stage (§3.1).

### 2.4 Reusing a holdout set safely

**Idea.** Every time a holdout set is used to make a choice, a little of it leaks into
the choices. After enough rounds an adaptive process can overfit even data it never saw
directly.

- The **reusable holdout** (Thresholdout) answers only when training and holdout
  disagree, adds noise to its answer, and bounds how much information escapes.
- The **Ladder** applies the same idea to leaderboards: it reveals a new score only when
  the gain is significant.
- **Alpha-investing and LORD** control false discoveries over an endless stream of tests,
  by earning error budget back with each discovery.

**Sources.**

- C. Dwork, V. Feldman, M. Hardt, T. Pitassi, O. Reingold, A. Roth, "The reusable
  holdout: Preserving validity in adaptive data analysis," *Science* 349(6248), 2015.
  [doi:10.1126/science.aaa9375](https://doi.org/10.1126/science.aaa9375),
  [arXiv:1506.02629](https://arxiv.org/abs/1506.02629)
- A. Blum, M. Hardt, "The Ladder: A Reliable Leaderboard for Machine Learning
  Competitions," *ICML*, 2015. [arXiv:1502.04585](https://arxiv.org/abs/1502.04585)
- D. P. Foster, R. A. Stine, "α-investing: a procedure for sequential control of expected
  false discoveries," *JRSS B* 70(2), 2008.
  [doi:10.1111/j.1467-9868.2007.00643.x](https://doi.org/10.1111/j.1467-9868.2007.00643.x)
- A. Javanmard, A. Montanari, "Online rules for control of false discovery rate and false
  discovery exceedance," *Annals of Statistics* 46(2), 2018.
  [arXiv:1603.09000](https://arxiv.org/abs/1603.09000)

**For us.** The loop is already a Ladder in spirit:

- The proposer sees **only the accept bit** from holdout. That is at most one bit per
  generation, never holdout numbers (`Feedback` carries dev results only).
- Holdout blocks rotate every `holdout_rotate` generations, so one block can leak at most
  about 10 bits.

Dwork et al. show that leakage this small keeps a holdout valid for a number of
adaptive queries far beyond what one generation asks. **No change was needed.** The
spy tests in `tests/rsi/` keep it that way, for the new rule too.

Alpha-investing would add a *run-level* guarantee: a bound on the expected false accepts
over the whole run, not just per test. It is listed as an open direction (§5), because
it would change how accept thresholds evolve over a run. That is a policy decision for
the owner, not a pure improvement.

### 2.5 Better proposers for noisy, bounded, continuous parameters

**Idea.** The **CMA-ES** samples candidates from a multivariate normal distribution and
learns its *covariance*, so it can follow ridges where several knobs must move together.

- The **(1+1)-CMA-ES** keeps one parent and one child per generation, the same shape as
  our loop. It controls its step size with a success rule (target 2/11, a refinement of
  Rechenberg's 1/5th rule).
- The **active** variant also learns from clearly bad steps, by shrinking the covariance
  in that direction.
- **Uncertainty-handling CMA-ES** re-evaluates candidates and raises the step size when
  rankings flip under noise.

**Sources.**

- N. Hansen, A. Ostermeier, "Completely Derandomized Self-Adaptation in Evolution
  Strategies," *Evolutionary Computation* 9(2), 2001.
  [doi:10.1162/106365601750190398](https://doi.org/10.1162/106365601750190398)
- C. Igel, T. Suttorp, N. Hansen, "A Computational Efficient Covariance Matrix Update and
  a (1+1)-CMA for Evolution Strategies," *GECCO*, 2006.
  [doi:10.1145/1143997.1144082](https://doi.org/10.1145/1143997.1144082)
- D. V. Arnold, N. Hansen, "Active Covariance Matrix Adaptation for the (1+1)-CMA-ES,"
  *GECCO*, 2010. [doi:10.1145/1830483.1830556](https://doi.org/10.1145/1830483.1830556)
- N. Hansen, A. S. P. Niederberger, L. Guzzella, P. Koumoutsakos, "A Method for Handling
  Uncertainty in Evolutionary Optimization With an Application to Feedback Control of
  Combustion," *IEEE TEC* 13(1), 2009.
  [doi:10.1109/TEVC.2008.924423](https://doi.org/10.1109/TEVC.2008.924423)
- N. Hansen, "The CMA Evolution Strategy: A Tutorial," 2016.
  [arXiv:1604.00772](https://arxiv.org/abs/1604.00772)

**Alternatives considered:**

- **Bayesian optimisation** with a noisy Gaussian-process model. It is strong at very
  small budgets but needs a GP library, and its cost per proposal grows with history.
  - J. Snoek, H. Larochelle, R. P. Adams, "Practical Bayesian Optimization of Machine
    Learning Algorithms," *NeurIPS*, 2012. [arXiv:1206.2944](https://arxiv.org/abs/1206.2944)
  - B. Letham, B. Karrer, G. Ottoni, E. Bakshy, "Constrained Bayesian Optimization with
    Noisy Experiments," *Bayesian Analysis* 14(2), 2019.
    [arXiv:1706.07094](https://arxiv.org/abs/1706.07094)
- **Adaptive operator selection**: a bandit that picks among proposers by recent success.
  - Á. Fialho, L. Da Costa, M. Schoenauer, M. Sebag, "Analyzing bandit-based adaptive
    operator selection mechanisms," *Annals of Mathematics and Artificial Intelligence*
    60, 2010. [doi:10.1007/s10472-010-9213-y](https://doi.org/10.1007/s10472-010-9213-y)

**For us.** Built as the `cma_es` proposer (§3.2): one candidate per generation, no new
dependencies, and its state checkpoints like the other proposers'. Adaptive operator
selection overlaps with the proposer portfolio the evolution harness is building, so
this framework only registers `cma_es` for that portfolio.

### 2.6 Open-ended and code-level self-improvement

**Idea.** These systems go beyond numbers:

- **The Gödel Machine** rewrites itself only after proving that the rewrite helps.
- **STOP** has a language model improve the scaffold that improves code.
- **FunSearch and AlphaEvolve** evolve programs, with an automatic evaluator as the judge.
- **Promptbreeder** evolves its own mutation prompts.
- **The Darwin Gödel Machine** keeps an archive of self-modifying coding agents.
- **POET** co-evolves environments and the agents that solve them.

**Sources.** Chapter 3 lists them in full. In addition:

- R. Wang, J. Lehman, J. Clune, K. O. Stanley, "Paired Open-Ended Trailblazer (POET),"
  2019. [arXiv:1901.01753](https://arxiv.org/abs/1901.01753)
- D. Manheim, S. Garrabrant, "Categorizing Variants of Goodhart's Law," 2018.
  [arXiv:1803.04585](https://arxiv.org/abs/1803.04585)

**For us.** Two lessons carry over:

1. **A fixed external judge is what makes the claims mean anything.** STOP even saw its
   improver try to turn off its own sandbox.
2. **An archive of stepping stones matters as much as the latest champion.**

Both are already rules here: the improver never grades itself, and the archive is
immutable. Code proposals stay review-only (`code_proposer.py`). Nothing in this chapter
loosens either rule.

---

## 3. What changed, and why

All new behaviour is **opt-in**. The defaults (`PairedBootstrapRule`,
`gaussian_hill_climb`) are untouched, and default runs are byte-identical to before.

### 3.1 `SequentialPairedRule` (in `arena/rsi/accept.py`)

A new acceptance rule. The loop recognises it through the `SequentialRule` protocol in
`types.py` and stages evaluation.

**Dev stage (racing).**

- Dev seeds are played in chunks: 25%, 50% and 100% of `dev_pairs`, never fewer than
  `min_pairs` (20).
- After each chunk, a candidate with paired z < `dev_futility_z` (0) stops. One with
  z ≥ `dev_pass_z` (3) and a positive mean passes straight on.
- When the best candidate of a batch was stopped, the generation is a dev rejection.

**Holdout stage (group-sequential).**

- The decision and extension seeds form one sample, looked at 25%, 50% and 100% of the
  way through. With 50 + 50 pairs, the looks fall at 25, 50 and 100 pairs.
- At look *k* the rule accepts if three things hold:
  - z ≥ c_k;
  - the relative gain is at least 2%;
  - no guard metric got worse beyond its tolerance.
- The boundaries c_k come from the O'Brien-Fleming-type spending function
  α(t) = 2(1 − Φ(z₁₋α/₂ / √t)), with one-sided α = 0.025.
- At look *k* the rule may spend only α(t_k) − α(t_{k−1}). By the union bound, the total
  chance of a false accept is therefore at most α, whatever the correlation between
  looks.
  - For looks at 25%, 50% and 100%, the boundaries are about 4.33, 2.96 and 1.99.
  - A simulation in `tests/rsi/test_sequential.py` checks the false-accept rate on
    Gaussian data.
- If z < `futility_z` (0) at an interim look, the candidate is rejected early. Futility
  stops only reject, so they cannot add false accepts.
- Failures and missing guards reject, as before.

**What it records.** The decision's `stats["holdout"]` records the z, the boundary, the
look and why it stopped. The report shows the alpha and the looks.

**Why.** It addresses both measured weaknesses of the default rule:

1. It spends many episodes on candidates whose fate is obvious.
2. Its error rate is slightly above nominal (§2.1).

### 3.2 `cma_es` (in `arena/rsi/proposers.py`)

`OnePlusOneCMA` is the (1+1)-CMA-ES of Igel et al. (2006), with Arnold and Hansen's
(2010) active update, working in the normalised [0, 1] parameter space.

**How it adapts its step size.** The smoothed success rate is pushed toward 2/11, with
c_p = 1/12 and damping d = 1 + n/2. σ stays within [0.005, 0.5].

**How it learns the covariance.**

- On accept, it updates an evolution path and a rank-one covariance, with
  c_c = 2/(n+2) and c_cov = 2/(n²+6).
- When a step's dev z is below −2, it applies an active negative update. The update is
  capped by Arnold and Hansen's 1/(2‖z‖²−1) rule, and is refused if it would break
  positive definiteness or push the condition number past 10⁶.
- It learns from the step *actually taken* after bounds clipping and integer rounding,
  not the step it drew.

**What it may see.** It reads only `Feedback` (the dev result and the accept bit), like
every proposer.

**Why.** Our parameters interact, and the hill climber moves one or two at a time.

### 3.3 Two new toy problems (in `arena/rsi/toys.py`)

- **`NoisyEllipsoid`** is a randomly rotated quadratic with condition number 100, so the
  good directions are diagonal.
- **`RareEvents`** gives Poisson counts around a Gaussian bump, scaled by a gamma
  "layout" factor shared across the seed. Its scores are sparse, mostly-zero counts,
  like kills. With `flat=True`, it is a rare-event pure-noise problem for false-accept
  checks.

The quadratic problem alone could not show either weakness the upgrades target.

---

## 4. Benchmark numbers

**Setup.** 20 seeded problems per row. Every configuration gets the same **episode**
budget, with 50 dev and 50 holdout pairs; the rare-event rows use 100 and 100. Scores are
the final champion's true score. Differences are paired by problem, with 95% bootstrap
CIs. Full tables and commands are in `experiments/2026-11-13-rsi-upgrades/README.md`.

### Final score: difference from the default (hill climb + bootstrap)

| Problem | hill climb + sequential | cma_es + bootstrap | cma_es + sequential |
|---|---|---|---|
| Quadratic 5-D, 12k episodes | +0.043 [−0.088, +0.180] | **+0.299 [+0.134, +0.504]** | +0.170 [−0.002, +0.372] |
| Ellipsoid 5-D, 12k | **+0.202 [+0.021, +0.446]** | **+1.104 [+0.562, +1.670]** | **+0.951 [+0.396, +1.512]** |
| Ellipsoid 10-D, 12k | **+2.714 [+0.635, +6.280]** | **+3.096 [+0.493, +7.102]** | **+4.038 [+1.652, +8.008]** |
| Rare events 5-D, 24k | +0.010 [−0.039, +0.074] | **+0.321 [+0.203, +0.421]** | **+0.289 [+0.161, +0.407]** |

Bold means the 95% CI excludes 0.

### Median episodes until regret first fell to 10% of the start

For the rare-event problem the target is 50%. The fraction is how many of the 20 problems
reached the target.

| Problem | hill climb + bootstrap | hill climb + sequential | cma_es + bootstrap | cma_es + sequential |
|---|---|---|---|---|
| Quadratic 5-D | 4,600 (20/20) | 2,225 (20/20) | 4,650 (20/20) | 2,065 (20/20) |
| Ellipsoid 5-D | 1,700 (12/20) | 790 (12/20) | 3,650 (18/20) | 1,640 (17/20) |
| Ellipsoid 10-D | 7,400 (7/20) | 4,490 (11/20) | 9,600 (11/20) | 4,290 (16/20) |
| Rare events 5-D | 4,400 (1/20) | 5,150 (1/20) | 6,400 (15/20) | 3,050 (15/20) |

### Pure noise

Every accept here is false. The setup is 10 seeds × 200 generations.

| Noise | Rule | Accepts per holdout test | Accepts per generation | Episodes |
|---|---|---|---|---|
| Gaussian | bootstrap (default) | 33/970 (3.4%) | 1.65% | 307,600 |
| Gaussian | sequential | 19/711 (2.7%) | 0.95% | 205,590 |
| Rare events | bootstrap (default) | 30/897 (3.3%) | 1.50% | 322,500 |
| Rare events | sequential | 12/702 (1.7%) | 0.60% | 225,480 |

### What the numbers say

- **`cma_es` beat the hill climber on all four problems.** The largest gains are where
  directions are diagonal (the ellipsoid) or the landscape is flat (rare events).
- **The sequential rule reached the target in 44–61% of the bootstrap rule's median
  episodes on every smooth problem.** On the 10-D ellipsoid it also raised the final
  score with either proposer.
- **On pure noise the sequential rule's per-test rates are consistent with its 2.5%
  design.** The bootstrap rule's are above it. The sequential rule also cut the
  per-generation false-accept rate by 42–60% and spent about 30% fewer episodes.
- **It is faster, not always better at the end.** The table below compares the
  sequential rule with the bootstrap rule for the same proposer, at the same budget:

  | Problem | hill climb: sequential − bootstrap | cma_es: sequential − bootstrap |
  |---|---|---|
  | Quadratic 5-D | +0.043 [−0.088, +0.180] | **−0.130 [−0.221, −0.045]** |
  | Ellipsoid 5-D | **+0.202 [+0.021, +0.446]** | **−0.153 [−0.280, −0.033]** |
  | Ellipsoid 10-D | **+2.714 [+0.635, +6.280]** | **+0.942 [+0.497, +1.473]** |
  | Rare events 5-D | +0.010 [−0.039, +0.074] | −0.032 [−0.119, +0.047] |

  With `cma_es`, the sequential rule finishes measurably *worse* on the two easy
  problems. Near the optimum each remaining gain is small, and a z test held at α = 2.5%
  demands more evidence than the bootstrap rule, which runs at about 3.4%. Every accept
  also moves `cma_es`'s step size and covariance, so fewer accepts slow its endgame. The
  sequential rule therefore pays off most when the budget is tight or the problem hard,
  and least in a long run on an easy problem.
- **The hill climber stalls on rare events with either rule** (1/20 reached the
  target). Most of its single-coordinate steps land on the flat region and are
  rejected, so its 1/5th rule shrinks σ to the minimum.

The defaults stay as they were. The snakes' real evaluation is far more expensive and
noisier than any toy, and the evolution harness should confirm the gains there before
either new piece becomes a default.

**How to enable them:**

- `make_proposer("cma_es")`, or `evolve --proposer cma_es` through a profile's proposer
  name;
- `Run(..., rule=SequentialPairedRule())`.

---

## 5. Open directions

1. **Use small-sample (Student t) boundaries.** The normal z test is slightly
   anti-conservative at the first look (25 pairs). Mapping each boundary through a t
   quantile with n − 1 degrees of freedom would fix this, but needs a t-quantile
   function. NumPy has none, and SciPy would be a new dependency.
2. **Anytime-valid intervals for counts.** Confidence sequences (Howard et al. 2021) for
   bounded or sub-exponential differences would allow a look after every game, with no
   normal approximation. They are attractive for kill counts, which are skewed.
3. **Run-level error control.** Alpha-investing or LORD would bound the expected number
   of false accepts across a whole run. Today the bound is per test, and a 200-generation
   run makes hundreds of tests.
4. **Uncertainty handling inside `cma_es`.** Hansen et al. (2009) re-evaluate candidates
   and raise σ when noise dominates. Here, the dev z could feed that rule directly.
5. **Restart strategies.** IPOP-style restarts with a larger σ would help when a lineage
   stalls on a plateau, as the hill climber does on rare events.
6. **A proposer portfolio with adaptive selection.** A bandit over proposers, rewarded by
   accepts per episode, could pick `cma_es` on problems with interacting knobs and the
   hill climber elsewhere. It belongs in the evolution harness.
7. **Thresholdout-style noise on the accept bit.** This is only worth adding if
   proposers start reading more than one bit per generation from holdout. Today they
   cannot.
