"""SequentialPairedRule: staged dev screening and group-sequential holdout looks."""

import json
from pathlib import Path

import numpy as np
import pytest
from rsi_helpers import quadratic_run
from test_toys import SpyProposer, ints_in

from arena.rsi import Budget, Run, RunConfig, make_proposer
from arena.rsi.accept import (
    GuardMetric,
    SequentialPairedRule,
    look_boundaries,
    obrien_fleming_spending,
    z_score,
)
from arena.rsi.store import read_json
from arena.rsi.toys import (
    CrashingEvaluator,
    NoisyQuadratic,
    PureNoise,
    RareEvents,
    SpyEvaluator,
)
from arena.rsi.types import Candidate, PairedResult, SequentialRule

RULE = SequentialPairedRule()


def result(diffs: list[float], base: float = 10.0, failures: int = 0, guards: dict | None = None):
    n = len(diffs)
    return PairedResult(
        tuple(range(n)),
        tuple(base + d for d in diffs),
        (base,) * n,
        {"guards": guards} if guards else {},
        failures,
    )


GOOD = [1.0 + 0.1 * ((i % 5) - 2) for i in range(200)]
DEV = result(GOOD[:50])


def test_spending_ends_at_alpha_and_boundaries_fall() -> None:
    spent = obrien_fleming_spending(0.025, (0.25, 0.5, 1.0))
    assert spent[0] < 1e-4 < spent[1] < spent[2] == pytest.approx(0.025)
    c = look_boundaries(0.025, (0.25, 0.5, 1.0))
    assert c[0] > c[1] > c[2] > 1.96 and c[2] < 2.0


def test_the_boundaries_keep_false_accepts_below_alpha() -> None:
    rng = np.random.default_rng(0)
    looks = (50, 100, 200)
    c = look_boundaries(0.025, [n / 200 for n in looks])
    sims = rng.standard_normal((20_000, 200))
    crossed = np.zeros(len(sims), dtype=bool)
    for n, bound in zip(looks, c, strict=True):
        x = sims[:, :n]
        crossed |= x.mean(axis=1) / (x.std(axis=1, ddof=1) / np.sqrt(n)) >= bound
    assert crossed.mean() <= 0.03


def test_z_score_handles_constant_samples() -> None:
    assert z_score(np.array([])) == 0.0
    assert z_score(np.zeros(5)) == 0.0
    assert z_score(np.ones(5)) == np.inf and z_score(-np.ones(5)) == -np.inf
    assert z_score(np.array([1.0, 3.0])) == pytest.approx(2.0 / (np.sqrt(2) / np.sqrt(2)))


def test_looks_respect_the_minimum_and_end_at_the_full_sample() -> None:
    assert RULE.holdout_looks(100, 100) == (50, 100, 200)
    assert RULE.holdout_looks(30, 30) == (20, 30, 60)
    assert SequentialPairedRule(use_extension=False).holdout_looks(100, 100) == (25, 50, 100)
    assert RULE.dev_looks(100) == (25, 50, 100)
    assert RULE.dev_looks(12) == (12,)
    with pytest.raises(ValueError):
        SequentialPairedRule(holdout_fractions=(0.5,))


def test_dev_interim_stops_the_clearly_worse_and_passes_the_clearly_better() -> None:
    assert RULE.dev_interim(result([-1.0 + 0.1 * (i % 3) for i in range(20)])) == "stop"
    assert RULE.dev_interim(result(GOOD[:20])) == "pass"
    assert RULE.dev_interim(result(GOOD[:10])) is None  # below min_pairs
    assert RULE.dev_interim(result([0.5 if i % 2 else -0.4 for i in range(20)])) is None
    assert RULE.dev_interim(result(GOOD[:5], failures=1)) == "stop"
    assert SequentialPairedRule(dev_pass_z=None).dev_interim(result(GOOD[:20])) is None


def test_a_clear_winner_is_accepted_at_the_first_look() -> None:
    d = RULE.decide_at(DEV, result(GOOD[:50]), (50, 100, 200))
    assert d is not None and d.accept and d.stats["holdout"]["stopped"] == "efficacy"
    assert d.stats["holdout"]["look"] == 1 and d.stats["holdout"]["ci"][0] > 0


def test_futility_and_the_last_look_reject() -> None:
    worse = result([-0.2 if i % 2 else 0.1 for i in range(50)])
    d = RULE.decide_at(DEV, worse, (50, 100, 200))
    assert d is not None and not d.accept and d.stats["holdout"]["stopped"] == "futility"
    unclear = result([0.15 if i % 2 else -0.1 for i in range(50)])
    assert RULE.decide_at(DEV, unclear, (50, 100, 200)) is None
    flat = result([1.0 if i % 2 else -1.0 for i in range(200)])
    d = RULE.decide_at(DEV, flat, (50, 100, 200))
    assert d is not None and not d.accept and d.stats["holdout"]["stopped"] == "final"
    with pytest.raises(ValueError, match="planned looks"):
        RULE.decide_at(DEV, result(GOOD[:60]), (50, 100, 200))


def test_gain_guards_and_failures_still_apply() -> None:
    tiny = result([0.1 + 0.001 * (i % 3) for i in range(200)])
    d = RULE.decide(DEV, tiny, np.random.default_rng(0))
    assert not d.accept and "minimum gain" in d.rationale
    rule = SequentialPairedRule(guards=(GuardMetric("deaths", 0.15),))
    bad = rule.decide(DEV, result(GOOD, guards={"deaths": (1.2, 1.0)}), np.random.default_rng(0))
    ok = rule.decide(DEV, result(GOOD, guards={"deaths": (1.1, 1.0)}), np.random.default_rng(0))
    missing = rule.decide(DEV, result(GOOD), np.random.default_rng(0))
    assert ok.accept and not bad.accept and "guard worse" in bad.rationale
    assert not missing.accept and "not reported" in missing.rationale
    failed = RULE.decide(DEV, result(GOOD, failures=1), np.random.default_rng(0))
    assert not failed.accept and "failures" in failed.rationale
    assert RULE.decide(result([-0.1] * 50), result(GOOD), np.random.default_rng(0)).stage == "dev"


def test_the_rule_round_trips_and_is_a_sequential_rule() -> None:
    rule = SequentialPairedRule(guards=(GuardMetric("deaths", 0.1),), futility_z=-0.5)
    assert SequentialPairedRule.from_dict(rule.to_dict()) == rule
    assert isinstance(rule, SequentialRule)
    from arena.rsi import PairedBootstrapRule

    assert not isinstance(PairedBootstrapRule(), SequentialRule)


def records(run_dir: Path) -> list[dict]:
    lines = (run_dir / "generations.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_a_sequential_run_replays_and_spends_fewer_episodes(tmp_path: Path) -> None:
    seq = quadratic_run(tmp_path / "a", generations=20, rule=SequentialPairedRule()).run()
    quadratic_run(tmp_path / "b", generations=20, rule=SequentialPairedRule()).run()
    assert (tmp_path / "a" / "generations.jsonl").read_text() == (
        tmp_path / "b" / "generations.jsonl"
    ).read_text()
    quadratic_run(tmp_path / "boot", generations=20).run()
    used = records(tmp_path / "a")[-1]["episodes"]
    assert seq.accepted >= 1 and used < records(tmp_path / "boot")[-1]["episodes"]
    held = [r["decision"]["stats"].get("holdout") for r in records(tmp_path / "a")]
    held = [h for h in held if h]
    assert held and all(h["n"] in h["looks"] and "stopped" in h for h in held)
    short = [f for r in records(tmp_path / "a") for f in r["feedback"] if f["dev"]]
    assert any(len(f["dev"]["seeds"]) < 30 for f in short), "no dev screen stopped early"
    assert "false-accept alpha" in (tmp_path / "a" / "report.md").read_text()


class Killer:
    def __init__(self, inner: NoisyQuadratic, after: int) -> None:
        self.inner, self.after, self.calls = inner, after, 0

    def evaluate(self, a: Candidate, b: Candidate, seeds: tuple) -> object:
        self.calls += 1
        if self.calls > self.after:
            raise KeyboardInterrupt
        return self.inner.evaluate(a, b, seeds)


def test_a_killed_sequential_run_resumes_identically(tmp_path: Path) -> None:
    rule = SequentialPairedRule()
    whole = quadratic_run(tmp_path / "whole", rule=rule).run()
    q = NoisyQuadratic(dim=3, problem_seed=1)
    with pytest.raises(KeyboardInterrupt):
        quadratic_run(tmp_path / "cut", rule=rule, evaluator=Killer(q, 9)).run()
    resumed = quadratic_run(tmp_path / "cut", rule=rule).run()
    assert resumed.champion == whole.champion
    assert (tmp_path / "whole" / "generations.jsonl").read_text() == (
        tmp_path / "cut" / "generations.jsonl"
    ).read_text()


@pytest.mark.parametrize(
    "noise", [PureNoise(dim=5, problem_seed=3), RareEvents(dim=5, problem_seed=3, flat=True)]
)
def test_pure_noise_is_almost_never_accepted(tmp_path: Path, noise: NoisyQuadratic) -> None:
    config = RunConfig(run_seed=3, problem="noise", budget=Budget(generations=200))
    run = Run(
        tmp_path,
        noise.space,
        noise,
        make_proposer("gaussian_hill_climb"),
        SequentialPairedRule(),
        config,
    )
    r = run.run()
    assert r.generations == 200 and r.accepted / 200 <= 0.05


def test_crashing_candidates_are_never_accepted(tmp_path: Path) -> None:
    q = NoisyQuadratic(dim=3, problem_seed=2)
    crashing = CrashingEvaluator(q)
    r = quadratic_run(
        tmp_path,
        generations=30,
        proposer="random_restart",
        evaluator=crashing,
        problem=q,
        rule=SequentialPairedRule(),
    ).run()
    assert not crashing.bad(r.champion)
    tried = [
        f
        for rec in records(tmp_path)
        for f in rec["feedback"]
        if crashing.bad(Candidate.from_dict(f["candidate"]))
    ]
    assert tried and not any(f["accepted"] for f in tried)


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
    r = Run(tmp_path, q.space, spy_eval, spy, SequentialPairedRule(), config).run()
    seeds = read_json(tmp_path / "seeds.json")
    hidden = set(seeds["holdout"]) | set(seeds["final"])
    assert r.accepted >= 1
    assert any(set(c) <= set(seeds["holdout"]) for c in spy_eval.calls)
    seen = set(ints_in(spy.seen))
    assert set(seeds["dev"]) & seen and not hidden & seen
