import json
from pathlib import Path

import numpy as np

from arena.rsi import PairedBootstrapRule, Run, RunConfig, make_proposer
from arena.rsi.harness import OPERATORS, AdaptiveHarness
from arena.rsi.toys import NoisyQuadratic
from arena.rsi.types import Budget, Candidate, Feedback, History, PairedResult, ParamSpec

SPACE = (ParamSpec("a", "float", -1.0, 1.0, 0.0), ParamSpec("b", "float", -1.0, 1.0, 0.0))
CHAMP = Candidate.make({"a": 0.0, "b": 0.0}, None, 0, "init", "")


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


def dev(diff: float, guards: dict[str, tuple[float, float]] | None = None) -> PairedResult:
    a = (diff + 0.1, diff - 0.1, diff)
    return PairedResult((1, 2, 3), a, (0.0, 0.0, 0.0), {"guards": guards or {}})


def test_make_proposer_knows_harness() -> None:
    assert isinstance(make_proposer("harness", batch=2), AdaptiveHarness)


def test_a_run_is_deterministic_and_resumes(tmp_path: Path) -> None:
    first = run(tmp_path / "a", AdaptiveHarness()).run()
    again = run(tmp_path / "b", AdaptiveHarness()).run()
    assert first.champion == again.champion
    a = (tmp_path / "a" / "generations.jsonl").read_text()
    assert a == (tmp_path / "b" / "generations.jsonl").read_text()
    half = run(tmp_path / "c", AdaptiveHarness(), generations=3)
    half.run()
    resumed = run(tmp_path / "c", AdaptiveHarness(), generations=6).run()
    assert resumed.champion == first.champion
    assert (tmp_path / "c" / "generations.jsonl").read_text() == a


def test_every_operator_gets_tried_and_candidates_name_it(tmp_path: Path) -> None:
    run(tmp_path, AdaptiveHarness(batch=3), generations=4).run()
    used = set()
    for line in (tmp_path / "generations.jsonl").read_text().splitlines():
        for f in json.loads(line)["feedback"]:
            used.add(f["candidate"]["proposer"].split("/")[1])
    assert used == set(OPERATORS)


def test_rewards_follow_dev_results_guards_and_accepts() -> None:
    h = AdaptiveHarness(penalties={"crashes": 1.0})
    good = h.reward(Feedback(1, CHAMP, False, "screened", dev(1.0)))
    bad = h.reward(Feedback(1, CHAMP, False, "screened", dev(-1.0)))
    crashy = h.reward(Feedback(1, CHAMP, False, "screened", dev(1.0, {"crashes": (2.0, 1.0)})))
    won = h.reward(Feedback(1, CHAMP, True, "holdout", dev(1.0)))
    assert bad < crashy < good < won
    assert h.reward(Feedback(1, CHAMP, False, "validate", None)) == 0.0


def test_learning_moves_weights_batch_and_operator_stats() -> None:
    h = AdaptiveHarness(batch=3, priors={"a": 2.0})
    assert h.weights == {"a": 2.0}
    rng = np.random.default_rng(0)
    hist = History(1, (), (CHAMP,))
    cands = [h.propose(CHAMP, hist, SPACE, rng) for _ in range(h.batch)]
    h.observe([Feedback(1, c, False, "screened", dev(-1.0)) for c in cands])
    assert h.batch == 4
    assert sum(s["n"] for s in h.stats.values()) == len(cands)
    cands = [h.propose(CHAMP, History(2, (), (CHAMP,)), SPACE, rng) for _ in range(h.batch)]
    h.observe([Feedback(2, cands[0], True, "holdout", dev(1.0))])
    assert h.batch == 3
    assert h.journal[-1]["generation"] == 2
    q = AdaptiveHarness(priors={"a": 2.0})
    q.load_state(json.loads(json.dumps(h.state())))
    assert q.state() == h.state()
    assert set(h.summary()) == {"batch", "operator_reward", "top_params"}
