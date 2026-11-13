# 2026-11-13 meta-run: the loop tunes its own hill climber

**Result: no measurable gain.** The outer loop accepted 2 small changes on holdout, but on
60 final toy problems that no proposer saw, the settings it kept were not distinguishably
better than the defaults. This is the honest outcome and is reported as is; the defaults
in `GaussianHillClimb` were left unchanged.

- **What it tunes:** `GaussianHillClimb`'s initial step size σ (0.01–0.5, log scale), its
  grow factor (1–3) and its shrink factor (0.5–0.99). Defaults: 0.15, 1.5, 0.9.
- **How a setting is scored:** for each outer seed, a fresh `NoisyQuadratic` (5 dims) and
  an inner `Run` of 30 generations with 100 dev and 100 holdout pairs; the score is the
  true score of the champion it ends with (0 is the optimum). Candidate and champion are
  paired on the same problems.
- **Outer loop:** run seed 0, 40 generations, 30 dev and 30 holdout pairs (2 blocks),
  paired bootstrap with a 2% minimum gain, 60 final pairs.
- **Reproduce:** `uv run python -m arena.cli rsi-meta --workers 4 --generations 40
  --pairs 30 --out runs/meta` (6 min 52 s on 4 cores in the cloud container). The result
  does not depend on the worker count.

| | σ | grow | shrink | Mean true score on 60 final problems |
|---|---|---|---|---|
| Defaults | 0.150 | 1.50 | 0.900 | −4.746 |
| Kept by the meta-run | 0.148 | 1.47 | 0.902 | −4.506 |

Difference +0.240, 95% CI [−0.233, +0.806]: the interval includes 0.

Accepted changes: generation 16 (holdout gain +8.8%, CI [+0.036, +0.873]) and
generation 23 (+6.7%, CI [+0.048, +0.568]). Both cleared the holdout test, yet the final
check did not confirm a gain. That is what the final seeds are for: over 40 generations
of holdout tests, a few small accepts can pass by chance.

Files: `config.json`, `generations.jsonl` (every decision), `archive/` (accepted
settings), `champion.json`, `report.md`.
