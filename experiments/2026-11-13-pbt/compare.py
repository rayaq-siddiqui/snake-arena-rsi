"""Equal-episode-budget comparison of proposers on toy quadratics (plan step 5.3).

Each proposer gets the same toy problems (one per seed) and the same episode budget, so
a proposer that screens several candidates a generation gets fewer generations. The
score is the true score of the final champion (0 is the optimum); the table pairs every
proposer with ``gaussian_hill_climb`` on the same problems.

    uv run python experiments/2026-11-13-pbt/compare.py --workers 4
"""

from __future__ import annotations

import argparse
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from arena.rsi import Budget, PairedBootstrapRule, Run, RunConfig, make_proposer
from arena.rsi.toys import NoisyQuadratic

PROPOSERS = ("gaussian_hill_climb", "pbt", "cross_entropy", "random_restart")


def one(task: tuple[str, int, int, int, int]) -> float:
    name, seed, dim, episodes, pairs = task
    problem = NoisyQuadratic(dim=dim, problem_seed=seed)
    config = RunConfig(
        run_seed=seed,
        problem=f"toy quadratic ({dim} dims)",
        dev_pairs=pairs,
        holdout_pairs=pairs,
        final_pairs=2,
        budget=Budget(episodes=episodes),
    )
    with tempfile.TemporaryDirectory(prefix="pbt-compare-") as tmp:
        run = Run(tmp, problem.space, problem, make_proposer(name), PairedBootstrapRule(), config)
        result = run.run()
    return problem.true_score(result.champion.params)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=20)
    p.add_argument("--dim", type=int, default=5)
    p.add_argument("--episodes", type=int, default=12_000)
    p.add_argument("--pairs", type=int, default=50)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--out", default=str(Path(__file__).with_name("results.json")))
    a = p.parse_args()
    tasks = [(n, s, a.dim, a.episodes, a.pairs) for n in PROPOSERS for s in range(a.seeds)]
    with ProcessPoolExecutor(a.workers) as pool:
        scores = list(pool.map(one, tasks))
    by = {n: scores[i * a.seeds : (i + 1) * a.seeds] for i, n in enumerate(PROPOSERS)}
    base = np.array(by["gaussian_hill_climb"])
    rng = np.random.default_rng(0)
    rows = {}
    for n, s in by.items():
        d = np.array(s) - base
        boot = rng.choice(d, size=(10_000, len(d))).mean(axis=1)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        rows[n] = {"mean": float(np.mean(s)), "diff": float(d.mean()), "ci": [float(lo), float(hi)]}
        print(f"{n:22s} mean {np.mean(s):8.3f}  vs hill climb {d.mean():+7.3f} [{lo:+.3f}, {hi:+.3f}]")
    Path(a.out).write_text(json.dumps({"settings": {k: v for k, v in vars(a).items() if k != "out"}, "results": rows, "scores": by}, indent=2))


if __name__ == "__main__":
    main()
