"""Meta-run (plan step 5.1): the RSI loop tunes its own default proposer.

The outer loop is an ordinary ``Run``. Its candidates are settings for
``GaussianHillClimb`` (initial sigma, the grow and shrink factors of its step-size rule),
and its evaluator scores a setting by letting a hill climber with those settings run the
inner loop on a toy problem:

- each outer seed picks one ``NoisyQuadratic`` instance (its optimum) and the inner run's
  seed, so a candidate and the champion meet exactly the same problem (paired seeds);
- the inner run gets a fixed number of generations and the toy suite's usual run settings;
- the score is the true score of the champion the inner run ends with (0 is the optimum),
  so a setting that gets closer to the optimum in the same budget scores higher.

The outer loop keeps the usual guarantees: disjoint dev / holdout / final seeds, so the
settings it keeps are checked on toy problems no proposer saw, and the meta-run can only
change the three settings below, never the toy, the acceptance rule or the inner loop.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

from arena.rsi.accept import PairedBootstrapRule
from arena.rsi.loop import Run, RunConfig
from arena.rsi.proposers import GaussianHillClimb
from arena.rsi.toys import NoisyQuadratic
from arena.rsi.types import Budget, Candidate, PairedResult, ParamSpec

META_SPACE = (
    ParamSpec("sigma", "float", 0.01, 0.5, 0.15, "log"),
    ParamSpec("grow", "float", 1.0, 3.0, 1.5),
    ParamSpec("shrink", "float", 0.5, 0.99, 0.9),
)


@dataclass(frozen=True)
class InnerTask:
    """Everything one inner run needs; picklable so runs can go to worker processes."""

    settings: tuple[tuple[str, float], ...]
    seed: int
    dim: int
    generations: int
    pairs: int


def inner_score(task: InnerTask) -> float:
    """True score of the champion a hill climber with ``settings`` finds on toy ``seed``."""
    problem = NoisyQuadratic(dim=task.dim, problem_seed=task.seed)
    s = dict(task.settings)
    proposer = GaussianHillClimb(sigma=s["sigma"], grow=s["grow"], shrink=s["shrink"])
    config = RunConfig(
        run_seed=task.seed,
        problem=f"meta inner, toy quadratic ({task.dim} dims)",
        dev_pairs=task.pairs,
        holdout_pairs=task.pairs,
        final_pairs=2,
        budget=Budget(generations=task.generations),
    )
    with tempfile.TemporaryDirectory(prefix="meta-inner-") as tmp:
        run = Run(tmp, problem.space, problem, proposer, PairedBootstrapRule(), config)
        result = run.run()
    return problem.true_score(result.champion.params)


@dataclass
class HillClimbTuning:
    """Evaluator for the meta-run: scores ``GaussianHillClimb`` settings on toy problems."""

    dim: int = 5
    generations: int = 30
    pairs: int = 100
    workers: int = 1
    _cache: dict[tuple[tuple[tuple[str, float], ...], int], float] = field(
        default_factory=dict, init=False, repr=False
    )

    def _settings(self, c: Candidate) -> tuple[tuple[str, float], ...]:
        return tuple(sorted((k, float(v)) for k, v in c.params.items()))

    def _scores(self, tasks: list[InnerTask]) -> list[float]:
        todo = [t for t in dict.fromkeys(tasks) if (t.settings, t.seed) not in self._cache]
        if self.workers > 1 and len(todo) > 1:
            with ProcessPoolExecutor(self.workers) as pool:
                done = list(pool.map(inner_score, todo))
        else:
            done = [inner_score(t) for t in todo]
        for t, s in zip(todo, done, strict=True):
            self._cache[(t.settings, t.seed)] = s
        return [self._cache[(t.settings, t.seed)] for t in tasks]

    def evaluate(self, a: Candidate, b: Candidate, seeds: Sequence[int]) -> PairedResult:
        def task(c: Candidate, seed: int) -> InnerTask:
            return InnerTask(self._settings(c), seed, self.dim, self.generations, self.pairs)

        scores = self._scores([task(a, s) for s in seeds] + [task(b, s) for s in seeds])
        n = len(seeds)
        return PairedResult(tuple(seeds), tuple(scores[:n]), tuple(scores[n:]))


def meta_run(
    out: str,
    generations: int = 15,
    run_seed: int = 0,
    evaluator: HillClimbTuning | None = None,
    pairs: int = 12,
    final_pairs: int = 60,
    baseline: Mapping[str, float] | None = None,
) -> Run:
    """The outer run, ready to ``run()``; re-running the same ``out`` resumes it."""
    config = RunConfig(
        run_seed=run_seed,
        problem="meta: GaussianHillClimb settings on toy quadratics",
        dev_pairs=pairs,
        holdout_pairs=pairs,
        holdout_blocks=2,
        dev_pool=2_000,
        final_pairs=final_pairs,
        budget=Budget(generations=generations),
    )
    return Run(
        out,
        META_SPACE,
        evaluator or HillClimbTuning(),
        GaussianHillClimb(),
        PairedBootstrapRule(),
        config,
        baseline=baseline,
    )
