"""Phase 3 section 10 and 11: the framework works on problems with known answers."""

import dataclasses
import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from rsi_helpers import quadratic_run

from arena.rsi import Budget, PairedBootstrapRule, Run, RunConfig, make_proposer
from arena.rsi.store import read_json
from arena.rsi.toys import (
    CrashingEvaluator,
    NoisyEllipsoid,
    NoisyQuadratic,
    PureNoise,
    RareEvents,
    SpyEvaluator,
)
from arena.rsi.types import Candidate, Feedback, History, ParamSpec


def full_run(
    run_dir: Path,
    problem: NoisyQuadratic,
    proposer: str,
    generations: int,
    seed: int,
    evaluator: Any = None,
) -> Run:
    config = RunConfig(run_seed=seed, problem="toy", budget=Budget(generations=generations))
    return Run(
        run_dir,
        problem.space,
        evaluator or problem,
        make_proposer(proposer),
        PairedBootstrapRule(),
        config,
    )


def gap_closed(problem: NoisyQuadratic, champion: Candidate, baseline: Candidate) -> float:
    """Share of the baseline's distance to the optimum's score (0) still left."""
    return problem.true_score(champion.params) / problem.true_score(baseline.params)


def test_hill_climb_reaches_the_optimum_and_beats_random_restart(tmp_path: Path) -> None:
    left: dict[str, list[float]] = {"gaussian_hill_climb": [], "random_restart": []}
    for name, results in left.items():
        for seed in range(10):
            q = NoisyQuadratic(dim=5, problem_seed=seed)
            r = full_run(tmp_path / f"{name}-{seed}", q, name, 60, seed).run()
            assert r.generations == 60
            results.append(gap_closed(q, r.champion, r.baseline))
    hill, rand = left["gaussian_hill_climb"], left["random_restart"]
    assert sum(x <= 0.10 for x in hill) >= 9, hill
    assert (
        np.mean(hill) < np.mean(rand) and sum(h < r for h, r in zip(hill, rand, strict=True)) >= 9
    )


def test_worse_candidates_are_rejected(tmp_path: Path) -> None:
    worse = rejected = 0
    for seed in range(4):
        q = NoisyQuadratic(dim=5, problem_seed=seed)
        full_run(tmp_path / str(seed), q, "random_restart", 40, seed).run()
        archive = {
            p.stem: read_json(p)["params"]
            for p in (tmp_path / str(seed) / "archive").glob("*.json")
        }
        for line in (tmp_path / str(seed) / "generations.jsonl").read_text().splitlines():
            rec = json.loads(line)
            for f in rec["feedback"]:
                champ = archive[rec["champion_before"]]
                if q.true_score(f["candidate"]["params"]) < q.true_score(champ):
                    worse += 1
                    rejected += not f["accepted"]
    assert worse >= 100
    assert rejected / worse >= 0.95


def test_pure_noise_is_almost_never_accepted(tmp_path: Path) -> None:
    noise = PureNoise(dim=5, problem_seed=3)
    r = full_run(tmp_path, noise, "gaussian_hill_climb", 200, 3).run()
    assert r.generations == 200
    assert r.accepted / 200 <= 0.05


def test_crashing_candidates_are_never_accepted(tmp_path: Path) -> None:
    q = NoisyQuadratic(dim=3, problem_seed=2)
    crashing = CrashingEvaluator(q)
    r = quadratic_run(
        tmp_path, generations=40, proposer="random_restart", evaluator=crashing, problem=q
    ).run()
    tried_bad = 0
    for line in (tmp_path / "generations.jsonl").read_text().splitlines():
        for f in json.loads(line)["feedback"]:
            cand = Candidate.from_dict(f["candidate"])
            if crashing.bad(cand):
                tried_bad += 1
                assert not f["accepted"]
    assert tried_bad >= 10
    assert not crashing.bad(r.champion)


def ints_in(obj: Any) -> Iterator[int]:
    if isinstance(obj, bool):
        return
    if isinstance(obj, int):
        yield obj
    elif isinstance(obj, float) and obj.is_integer():
        yield int(obj)
    elif isinstance(obj, np.ndarray):
        yield from ints_in(obj.tolist())
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            yield from ints_in(getattr(obj, f.name))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from ints_in(k)
            yield from ints_in(v)
    elif isinstance(obj, list | tuple | set | frozenset):
        for v in obj:
            yield from ints_in(v)


class SpyProposer:
    """Wraps a proposer and keeps everything the loop hands it."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name, self.batch = inner.name, inner.batch
        self.seen: list[Any] = []

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        self.seen.append((champion, history, space))
        return self.inner.propose(champion, history, space, rng)

    def observe(self, feedback: Sequence[Feedback]) -> None:
        self.seen.append(tuple(feedback))
        self.inner.observe(feedback)

    def state(self) -> dict[str, Any]:
        return self.inner.state()

    def load_state(self, state: Any) -> None:
        self.inner.load_state(state)


def test_the_proposer_never_sees_holdout_or_final_seeds(tmp_path: Path) -> None:
    q = NoisyQuadratic(dim=3, problem_seed=4)
    spy_eval = SpyEvaluator(q)
    spy = SpyProposer(make_proposer("cross_entropy"))
    config = RunConfig(
        run_seed=4,
        problem="toy",
        dev_pairs=30,
        holdout_pairs=30,
        dev_pool=400,
        budget=Budget(generations=15),
    )
    r = Run(tmp_path, q.space, spy_eval, spy, PairedBootstrapRule(resamples=2000), config).run()
    seeds = read_json(tmp_path / "seeds.json")
    hidden = set(seeds["holdout"]) | set(seeds["final"])
    holdout_calls = [c for c in spy_eval.calls if set(c) <= set(seeds["holdout"])]
    assert holdout_calls and r.accepted >= 1, "the run never reached holdout"
    seen = set(ints_in(spy.seen))
    assert set(seeds["dev"]) & seen, "the spy should at least see dev seeds"
    assert not hidden & seen


def test_the_ellipsoid_is_a_rotated_badly_scaled_bowl() -> None:
    e = NoisyEllipsoid(dim=4, problem_seed=2)
    best = {f"x{i}": float(v) for i, v in enumerate(e.optimum)}
    assert e.true_score(best) == 0.0
    assert np.allclose(e.rotation @ e.rotation.T, np.eye(4))
    assert np.isclose(e.weights.mean(), 1.0)
    assert np.isclose(e.weights.max() / e.weights.min(), e.condition)
    again = NoisyEllipsoid(dim=4, problem_seed=2)
    assert np.array_equal(again.rotation, e.rotation)
    c = Candidate.make(best, None, 0, "t", "")
    assert e.score(c, 7) == again.score(c, 7)


def test_rare_events_are_counts_that_peak_at_the_optimum() -> None:
    r = RareEvents(dim=3, problem_seed=1)
    best = {f"x{i}": float(v) for i, v in enumerate(r.optimum)}
    far = {f"x{i}": -float(np.sign(v)) * 5.0 for i, v in enumerate(r.optimum)}
    assert r.true_score(best) == r.peak and r.true_score(far) < 0.1 * r.peak
    c = Candidate.make(best, None, 0, "t", "")
    scores = [r.score(c, s) for s in range(400)]
    assert all(s == int(s) >= 0 for s in scores)
    assert abs(np.mean(scores) - r.peak) < 0.2
    assert scores == [r.score(c, s) for s in range(400)]
    flat = RareEvents(dim=3, problem_seed=1, flat=True, peak=0.3)
    assert flat.true_score(far) == flat.true_score(best) == 0.3
