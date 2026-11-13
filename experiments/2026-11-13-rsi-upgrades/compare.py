"""Equal-episode-budget benchmark of RSI framework upgrades on toy problems.

Every configuration (proposer x acceptance rule) gets the same toy problems (one per
seed) and the same episode budget. Scores are true scores of the final champion (0 is the
optimum; higher is better), compared with the default configuration
(``gaussian_hill_climb`` + ``PairedBootstrapRule``) paired by problem, with a 95%
bootstrap CI over problems. It also reports the episodes each configuration needed before
its champion's regret (optimum minus true score) first fell to ``--target`` (default 10%)
of the baseline's, and how many accepted candidates were not truly better.

    uv run python experiments/2026-11-13-rsi-upgrades/compare.py --workers 2
    uv run python experiments/2026-11-13-rsi-upgrades/compare.py --problem ellipsoid
    uv run python experiments/2026-11-13-rsi-upgrades/compare.py --errors   # noise / worse
"""

from __future__ import annotations

import argparse
import json
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from arena.rsi import Budget, PairedBootstrapRule, Run, RunConfig, make_proposer
from arena.rsi.accept import SequentialPairedRule
from arena.rsi.store import read_json
from arena.rsi.toys import PROBLEMS, PureNoise, RareEvents
from arena.rsi.types import AcceptanceRule

RULES: dict[str, Any] = {
    "bootstrap": lambda: PairedBootstrapRule(),
    "sequential": lambda: SequentialPairedRule(),
    "seq-lenient": lambda: SequentialPairedRule(futility_z=-0.5, dev_futility_z=-0.5),
    "seq-strict": lambda: SequentialPairedRule(futility_z=0.5),
    "seq-nopass": lambda: SequentialPairedRule(dev_pass_z=None),
    "seq-min10": lambda: SequentialPairedRule(min_pairs=10),
}
DEFAULT_CONFIGS = (
    "gaussian_hill_climb+bootstrap",
    "gaussian_hill_climb+sequential",
    "cma_es+bootstrap",
    "cma_es+sequential",
    "random_restart+sequential",
)


def make_rule(name: str) -> AcceptanceRule:
    rule: AcceptanceRule = RULES[name]()
    return rule


def one(task: tuple[str, str, int, int, int, int, float]) -> dict[str, Any]:
    config_name, problem_name, seed, dim, episodes, pairs, target = task
    proposer, rule = config_name.split("+")
    problem = PROBLEMS[problem_name](dim=dim, problem_seed=seed)
    config = RunConfig(
        run_seed=seed,
        problem=f"toy {problem_name} ({dim} dims)",
        dev_pairs=pairs,
        holdout_pairs=pairs,
        final_pairs=2,
        budget=Budget(episodes=episodes),
    )
    with tempfile.TemporaryDirectory(prefix="rsi-upgrades-") as tmp:
        run = Run(tmp, problem.space, problem, make_proposer(proposer), make_rule(rule), config)
        result = run.run()
        records = [
            json.loads(x) for x in (Path(tmp) / "generations.jsonl").read_text().splitlines()
        ]
        params = {p.stem: read_json(p)["params"] for p in (Path(tmp) / "archive").glob("*.json")}
    best = problem.true_score({f"x{i}": float(v) for i, v in enumerate(problem.optimum)})
    gap = best - problem.true_score(result.baseline.params)
    to_target = None
    for rec in records:
        if best - problem.true_score(params[rec["champion_after"]]) <= target * gap:
            to_target = rec["episodes"]
            break
    accepted = [r for r in records if r["decision"]["accept"]]
    worse = sum(
        1
        for r in accepted
        if problem.true_score(params[r["champion_after"]])
        <= problem.true_score(params[r["champion_before"]])
    )
    return {
        "score": problem.true_score(result.champion.params),
        "to_target": to_target,
        "generations": result.generations,
        "accepted": result.accepted,
        "accepted_not_better": worse,
        "episodes": records[-1]["episodes"] if records else 0,
    }


def ci(d: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    boot = rng.choice(d, size=(10_000, len(d))).mean(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return float(lo), float(hi)


def compare(a: argparse.Namespace) -> dict[str, Any]:
    configs = a.configs.split(",") if a.configs else list(DEFAULT_CONFIGS)
    tasks = [
        (c, a.problem, s, a.dim, a.episodes, a.pairs, a.target)
        for c in configs
        for s in range(a.seeds)
    ]
    with ProcessPoolExecutor(a.workers) as pool:
        out = list(pool.map(one, tasks))
    by = {c: out[i * a.seeds : (i + 1) * a.seeds] for i, c in enumerate(configs)}
    base = np.array([r["score"] for r in by[configs[0]]])
    rng = np.random.default_rng(0)
    rows: dict[str, Any] = {}
    print(f"{a.problem} {a.dim}-D, {a.episodes:,} episodes, {a.pairs} pairs, {a.seeds} problems")
    for c, rs in by.items():
        s = np.array([r["score"] for r in rs])
        d = s - base
        lo, hi = ci(d, rng) if c != configs[0] else (0.0, 0.0)
        reached = [r["to_target"] for r in rs if r["to_target"] is not None]
        rows[c] = {
            "mean": float(s.mean()),
            "diff": float(d.mean()),
            "ci": [lo, hi],
            "reached_target": len(reached),
            "median_episodes_to_target": float(np.median(reached)) if reached else None,
            "mean_generations": float(np.mean([r["generations"] for r in rs])),
            "accepted": int(sum(r["accepted"] for r in rs)),
            "accepted_not_better": int(sum(r["accepted_not_better"] for r in rs)),
        }
        r = rows[c]
        med = r["median_episodes_to_target"]
        print(
            f"{c:34s} mean {s.mean():8.3f}  vs {configs[0]} {d.mean():+7.3f} "
            f"[{lo:+.3f}, {hi:+.3f}]  target {r['reached_target']}/{len(rs)} "
            f"median eps {med if med is None else int(med)}  gens {r['mean_generations']:.0f}  "
            f"accepts {r['accepted']} (not better {r['accepted_not_better']})"
        )
    return {"results": rows, "raw": by}


NOISE = {
    "gaussian": lambda seed: PureNoise(dim=5, problem_seed=seed),
    "rare": lambda seed: RareEvents(dim=5, problem_seed=seed, peak=0.3, flat=True),
}


def noise_task(task: tuple[str, str, int, int, int]) -> dict[str, int]:
    kind, rule, seed, generations, pairs = task
    problem = NOISE[kind](seed)
    config = RunConfig(
        run_seed=seed,
        problem="pure noise",
        dev_pairs=pairs,
        holdout_pairs=pairs,
        final_pairs=2,
        budget=Budget(generations=generations),
    )
    with tempfile.TemporaryDirectory(prefix="rsi-noise-") as tmp:
        prop = make_proposer("gaussian_hill_climb")
        result = Run(tmp, problem.space, problem, prop, make_rule(rule), config).run()
        records = [
            json.loads(x) for x in (Path(tmp) / "generations.jsonl").read_text().splitlines()
        ]
    holdout = sum(1 for r in records if r["decision"]["stage"] == "holdout")
    return {
        "accepted": result.accepted,
        "generations": result.generations,
        "holdout_tests": holdout,
        "episodes": records[-1]["episodes"],
    }


def errors(a: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {}
    rules = ("bootstrap", "sequential", "seq-min10")
    for kind, rule in ((k, r) for k in NOISE for r in rules):
        tasks = [(kind, rule, s, 200, a.pairs) for s in range(a.seeds)]
        with ProcessPoolExecutor(a.workers) as pool:
            rs = list(pool.map(noise_task, tasks))
        acc = sum(r["accepted"] for r in rs)
        gens = sum(r["generations"] for r in rs)
        tests = sum(r["holdout_tests"] for r in rs)
        eps = sum(r["episodes"] for r in rs)
        out[f"{kind}+{rule}"] = {
            "accepted": acc,
            "generations": gens,
            "holdout_tests": tests,
            "episodes": eps,
        }
        print(
            f"pure noise ({kind}), {rule:10s}: {acc} accepts in {gens} generations "
            f"({acc / gens:.2%}; {acc}/{tests} holdout tests), {eps:,} episodes"
        )
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=20)
    p.add_argument("--problem", default="quadratic", choices=sorted(PROBLEMS))
    p.add_argument("--dim", type=int, default=5)
    p.add_argument("--episodes", type=int, default=12_000)
    p.add_argument("--pairs", type=int, default=50)
    p.add_argument("--target", type=float, default=0.1, help="regret target, share of start")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--configs", help="comma-separated proposer+rule; the first is the base")
    p.add_argument("--errors", action="store_true", help="pure-noise false-accept check")
    p.add_argument("--out")
    a = p.parse_args()
    data = errors(a) if a.errors else compare(a)
    if a.out:
        settings = {k: v for k, v in vars(a).items() if k != "out"}
        Path(a.out).write_text(json.dumps({"settings": settings, **data}, indent=2) + "\n")


if __name__ == "__main__":
    main()
