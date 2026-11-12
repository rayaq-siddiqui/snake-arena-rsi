# 2026-11-12 baseline: five lineages, experiment profile

**Result: no lineage improved.** All five lineages stopped after 4 generations with 0
accepted changes, so every champion is still its hand-set generation-0 self. This is
the honest outcome of the pre-set protocol, and it is reported as is.

> This used the reduced `experiment` profile (24 × 24 board, 2,000-tick episodes,
> 40 dev + 40 holdout pairs, 100 final pairs), **not** the specified default experiment.
> See `specs/phase-4-snake-rsi.md`, As built, for why the profile exists.

- **View it:** open [`dashboard.html`](dashboard.html) in a browser, or read
  [`report.md`](report.md) (charts: [`progress.svg`](progress.svg)).
- **Reproduce:** `uv run python -m arena.cli evolve --profile experiment --generations 10
  --run-id 2026-11-12-experiment --workers 4`, then
  `uv run python -m arena.cli report runs/2026-11-12-experiment --workers 4`. The
  decisions do not depend on the worker count.
- **Watch it:** `uv run python -m arena.cli watch --run experiments/2026-11-12-baseline`.
- **Run setup:** run seed 0, `gaussian_hill_climb`, min gain 2%, patience 4. The
  generation budget was 10, but every lineage ran out of patience first. Code hash
  `7938b639809c2627` (`arena/rsi`); the run started at commit 35f7d75.

## What happened

| | Hunter | Survivor | Trapper | Predictor | Opportunist |
|---|---|---|---|---|---|
| Proposals | 4 | 4 | 4 | 4 | 4 |
| Reached holdout | 1 | 3 | 2 | 2 | 1 |
| Accepted | 0 | 0 | 0 | 0 | 0 |
| Kills / 1k ticks vs reference (95% CI) | 0.035 [0.010, 0.060] | 0.005 [0, 0.015] | 0.005 [0, 0.015] | 0.110 [0.070, 0.155] | 0.010 [0, 0.025] |

The closest call was Hunter's generation 2 proposal (`w_territory 20 -> -23.34`). It
showed a +12.3% holdout gain, but the 95% interval [-0.062, +0.175] reached zero, and its
deaths per 1,000 alive ticks rose from 0.12 to 5.07. Both the interval rule and the death
guard would have rejected it.

## Why nothing passed, as far as the data shows

- **Kills are rare.** Even on 24 × 24, a pre-run probe at the reference context found
  only 1-12 of 40 paired seeds per lineage with any kill, so most paired differences are
  exactly 0. A 40 + 40 pair
  budget then has little power to detect a 2% gain.
- **Many proposals change no outcome.** 5 of 20 proposals had a dev difference
  of exactly zero: over the 40 dev seeds the candidate and the champion scored the same
  total kills.
- **Patience 4** stopped every lineage after its fourth straight reject.

These are hypotheses for a follow-up experiment, which must be pre-registered and kept
separate from this baseline. They are not reasons to re-run this one.

## Cost

Wall time per generation on a 4-core cloud container with 4 workers: 747, 755, 712 and
434 s (640, 720, 640 and 400 episodes). The report took about 12 minutes.
