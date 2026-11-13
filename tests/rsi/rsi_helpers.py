from pathlib import Path
from typing import Any

from arena.rsi import Budget, PairedBootstrapRule, Run, RunConfig, make_proposer
from arena.rsi.toys import NoisyQuadratic


def quadratic_run(
    run_dir: Path,
    generations: int = 12,
    proposer: str = "gaussian_hill_climb",
    evaluator: Any = None,
    problem: NoisyQuadratic | None = None,
    rule: Any = None,
    **config: Any,
) -> Run:
    q = problem or NoisyQuadratic(dim=3, problem_seed=1)
    cfg = RunConfig(
        run_seed=config.pop("run_seed", 5),
        problem="quadratic",
        dev_pairs=config.pop("dev_pairs", 30),
        holdout_pairs=config.pop("holdout_pairs", 30),
        dev_pool=config.pop("dev_pool", 500),
        final_pairs=config.pop("final_pairs", 40),
        budget=Budget(generations=generations, **config.pop("budget", {})),
        **config,
    )
    rule = rule or PairedBootstrapRule(resamples=2000)
    return Run(run_dir, q.space, evaluator or q, make_proposer(proposer), rule, cfg)
