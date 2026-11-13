import json
import re
from pathlib import Path

import pytest

from arena.rsi import PairedBootstrapRule, Run, RunConfig
from arena.rsi.coach import HarnessCoach, parse_patch
from arena.rsi.harness import OPERATORS, AdaptiveHarness
from arena.rsi.llm import Reply
from arena.rsi.toys import NoisyQuadratic
from arena.rsi.types import Budget


def run(tmp: Path, harness: AdaptiveHarness, generations: int = 6) -> Run:
    q = NoisyQuadratic(dim=3, problem_seed=1)
    cfg = RunConfig(
        run_seed=3,
        problem="quadratic",
        dev_pairs=10,
        holdout_pairs=10,
        dev_pool=200,
        final_pairs=10,
        budget=Budget(generations=generations),
    )
    return Run(tmp, q.space, q, harness, PairedBootstrapRule(resamples=200), cfg)


REPLY = json.dumps(
    {
        "operator_bias": {"cma_es": 0.7, "random_restart": -3, "rm -rf": 1},
        "param_priors": {"x0": 9.0, "x1": 0.1, "nope": 2.0},
        "explore": 0.5,
        "max_batch": 7.6,
        "rationale": "cma_es wins on dev; x0 matters.",
        "acceptance": {"min_gain": 0},
    }
)


class Fake:
    def __init__(self, text: str = REPLY, fail: bool = False, empty: int = 0) -> None:
        self.text, self.fail, self.empty = text, fail, empty
        self.prompts: list[str] = []

    def __call__(self, system: str, prompt: str) -> Reply:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("network down")
        if self.empty > 0:
            self.empty -= 1
            return Reply("", 100, 4096, dollars=0.01)
        return Reply(self.text, 100, 50, dollars=0.01)


def coach(tmp: Path, fake: Fake, **kw: object) -> HarnessCoach:
    return HarnessCoach("win", complete=fake, audit_path=tmp / "audit.jsonl", **kw)  # type: ignore[arg-type]


def test_patches_keep_only_known_names_and_clip_every_number() -> None:
    patch = parse_patch("Sure! " + REPLY + " {trailing}", list(OPERATORS), ["x0", "x1"])
    assert patch["operator_bias"] == {"random_restart": -1.0, "cma_es": 0.7}
    assert patch["param_priors"] == {"x0": 4.0, "x1": 0.25}
    assert patch["explore"] == 0.5 and patch["max_batch"] == 6
    assert "acceptance" not in patch
    with pytest.raises(ValueError):
        parse_patch("no json here", list(OPERATORS), ["x0"])


def test_the_coach_rewrites_the_harness_and_logs_it(tmp_path: Path) -> None:
    fake = Fake()
    h = AdaptiveHarness(coach=coach(tmp_path, fake, every=2))
    run(tmp_path / "run", h, generations=4).run()
    assert len(fake.prompts) == 2
    assert h.bias == {"cma_es": 0.7, "random_restart": -1.0}
    assert h.priors["x0"] == 4.0 and h.explore == 0.5 and h.max_batch == 6
    assert sum("coach" in e for e in h.journal) == 2
    audit = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert [a["generation"] for a in audit] == [2, 4]
    assert audit[0]["patch"]["max_batch"] == 6
    assert h.summary()["coached"]["bias"] == {"cma_es": 0.7, "random_restart": -1.0}


def test_the_coach_never_sees_holdout_or_final_seeds(tmp_path: Path) -> None:
    fake = Fake()
    r = run(tmp_path / "run", AdaptiveHarness(coach=coach(tmp_path, fake, every=1)), 3)
    r.run()
    seeds = r.store.seeds()
    hidden = {int(s) for s in (*seeds["holdout"], *seeds["final"])}
    assert fake.prompts
    for prompt in fake.prompts:
        assert "seed" not in prompt.lower()
        assert not {int(n) for n in re.findall(r"\d{4,}", prompt)} & hidden


def test_state_round_trips_the_patch(tmp_path: Path) -> None:
    h = AdaptiveHarness(coach=coach(tmp_path, Fake(), every=1))
    run(tmp_path / "run", h, generations=2).run()
    fresh = AdaptiveHarness(coach=coach(tmp_path, Fake(), every=1))
    fresh.load_state(json.loads(json.dumps(h.state())))
    assert fresh.state() == h.state()
    assert fresh.coach is not None and fresh.coach.calls == 2


def test_failed_calls_and_spent_budgets_leave_the_harness_alone(tmp_path: Path) -> None:
    h = AdaptiveHarness(coach=coach(tmp_path, Fake(fail=True), every=1))
    run(tmp_path / "a", h, generations=2).run()
    assert h.bias == {} and h.explore == 1.0
    assert h.coach is not None and h.coach.failures == 2
    broke = Fake()
    h = AdaptiveHarness(coach=coach(tmp_path, broke, every=1, max_dollars=0.015))
    run(tmp_path / "b", h, generations=4).run()
    assert len(broke.prompts) == 2


def test_without_a_coach_the_harness_is_unchanged(tmp_path: Path) -> None:
    plain = run(tmp_path / "a", AdaptiveHarness(), generations=3).run()
    idle = HarnessCoach("win", every=99, complete=Fake())
    coached = run(tmp_path / "b", AdaptiveHarness(coach=idle), generations=3).run()
    assert plain.champion == coached.champion
    assert "coached" not in AdaptiveHarness().summary()


def test_an_empty_reply_is_asked_once_more(tmp_path: Path) -> None:
    fake = Fake(empty=1)
    c = coach(tmp_path, fake)
    patch = c.advise(2, {"parameters": []}, list(OPERATORS), ["x0"])
    assert patch is not None and patch["max_batch"] == 6
    assert c.calls == 2 and c.dollars == pytest.approx(0.02)
    silent = coach(tmp_path, Fake(empty=5))
    assert silent.advise(2, {}, list(OPERATORS), ["x0"]) is None
    assert silent.calls == 2 and silent.failures == 1
