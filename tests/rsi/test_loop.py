import json
from pathlib import Path

import numpy as np
import pytest
from helpers import quadratic_run

from arena.rsi.store import Archive, read_json
from arena.rsi.toys import NoisyQuadratic
from arena.rsi.types import Candidate


def test_a_run_writes_the_specified_layout(tmp_path: Path) -> None:
    result = quadratic_run(tmp_path).run()
    for name in ("config.json", "seeds.json", "generations.jsonl", "champion.json", "report.md"):
        assert (tmp_path / name).exists(), name
    records = [
        json.loads(line) for line in (tmp_path / "generations.jsonl").read_text().splitlines()
    ]
    assert [r["generation"] for r in records] == list(range(1, 13))
    assert result.accepted >= 1 and result.stop_reason == "generation budget"
    archived = {p.stem for p in (tmp_path / "archive").glob("*.json")}
    assert result.baseline.id in archived and result.champion.id in archived
    assert len(archived) == result.accepted + 1
    assert read_json(tmp_path / "champion.json")["id"] == result.champion.id
    config = read_json(tmp_path / "config.json")
    assert config["code_hash"] and config["framework_version"] == 1
    report = (tmp_path / "report.md").read_text()
    assert "## Decisions" in report and "final seeds" in report


def test_the_same_config_replays_to_the_same_decisions(tmp_path: Path) -> None:
    quadratic_run(tmp_path / "a").run()
    quadratic_run(tmp_path / "b").run()
    a = (tmp_path / "a" / "generations.jsonl").read_text()
    assert a and a == (tmp_path / "b" / "generations.jsonl").read_text()
    quadratic_run(tmp_path / "c", run_seed=6).run()
    assert a != (tmp_path / "c" / "generations.jsonl").read_text()


class Killer:
    """Evaluator that dies like a killed process after a number of calls."""

    def __init__(self, inner: NoisyQuadratic, after: int) -> None:
        self.inner, self.after, self.calls = inner, after, 0

    def evaluate(self, a: Candidate, b: Candidate, seeds: tuple) -> object:
        self.calls += 1
        if self.calls > self.after:
            raise KeyboardInterrupt
        return self.inner.evaluate(a, b, seeds)


@pytest.mark.parametrize("after", [1, 7, 16])
def test_kill_and_resume_equals_an_uninterrupted_run(tmp_path: Path, after: int) -> None:
    whole = quadratic_run(tmp_path / "whole", proposer="cross_entropy").run()
    q = NoisyQuadratic(dim=3, problem_seed=1)
    with pytest.raises(KeyboardInterrupt):
        quadratic_run(tmp_path / "cut", proposer="cross_entropy", evaluator=Killer(q, after)).run()
    resumed = quadratic_run(tmp_path / "cut", proposer="cross_entropy").run()
    for name in ("generations.jsonl", "champion.json", "seeds.json"):
        assert (tmp_path / "whole" / name).read_text() == (tmp_path / "cut" / name).read_text()
    assert resumed.champion == whole.champion


def test_a_half_written_generation_is_dropped_on_resume(tmp_path: Path) -> None:
    quadratic_run(tmp_path / "whole", generations=6).run()
    quadratic_run(tmp_path / "cut", generations=4).run()
    with open(tmp_path / "cut" / "generations.jsonl", "a") as f:
        f.write('{"generation": 5, "junk": true}\n')
    quadratic_run(tmp_path / "cut", generations=6).run()
    assert (tmp_path / "whole" / "generations.jsonl").read_text() == (
        tmp_path / "cut" / "generations.jsonl"
    ).read_text()


def test_resume_refuses_a_different_run(tmp_path: Path) -> None:
    quadratic_run(tmp_path, generations=2).run()
    with pytest.raises(ValueError, match="different run"):
        quadratic_run(tmp_path, generations=2, run_seed=99).run()
    with pytest.raises(ValueError, match="different run"):
        quadratic_run(tmp_path, generations=2, proposer="random_restart").run()


def test_budgets_patience_and_the_stop_file_end_a_run(tmp_path: Path) -> None:
    r = quadratic_run(tmp_path / "ep", generations=100, budget={"episodes": 300}).run()
    assert r.stop_reason == "episode budget" and r.generations < 100
    r = quadratic_run(
        tmp_path / "pat", generations=100, proposer="random_restart", patience=3
    ).run()
    assert r.stop_reason == "no accept in 3 generations"
    (tmp_path / "stop").mkdir()
    (tmp_path / "stop" / "STOP").touch()
    r = quadratic_run(tmp_path / "stop", generations=100).run()
    assert r.stop_reason == "stop file" and r.generations == 0
    ticks = iter(range(0, 10**6, 10))
    run = quadratic_run(tmp_path / "time", generations=100, budget={"seconds": 25.0})
    run.clock = lambda: float(next(ticks))
    r = run.run()
    assert r.stop_reason == "time budget" and r.generations == 3


def test_a_budget_can_be_extended_on_resume(tmp_path: Path) -> None:
    quadratic_run(tmp_path / "whole", generations=8).run()
    quadratic_run(tmp_path / "grow", generations=3).run()
    r = quadratic_run(tmp_path / "grow", generations=8).run()
    assert r.generations == 8
    assert (tmp_path / "whole" / "generations.jsonl").read_text() == (
        tmp_path / "grow" / "generations.jsonl"
    ).read_text()


def test_archive_entries_are_immutable_and_serve_opponents(tmp_path: Path) -> None:
    archive = Archive(tmp_path)
    members = [Candidate.make({"x": float(i)}, None, i, "t", "") for i in range(7)]
    for m in members:
        archive.add(m)
    again = Archive(tmp_path)
    again.add(members[2])
    assert again.members == [members[2]]
    with pytest.raises(RuntimeError, match="different content"):
        archive.add(Candidate(members[3].id, {"x": 99.0}, None, 3, "t", ""))
    assert archive.opponents("latest", 2) == [members[6], members[5]]
    assert archive.opponents("baseline") == [members[0]]
    assert archive.opponents("milestones", 5, every=3) == [members[6], members[3], members[0]]
    picks = archive.opponents("uniform", 20, rng=np.random.default_rng(0))
    assert len(picks) == 20 and set(p.id for p in picks) <= {m.id for m in members}


def test_a_crashing_evaluator_counts_as_failures(tmp_path: Path) -> None:
    class Boom:
        def evaluate(self, a: Candidate, b: Candidate, seeds: tuple) -> object:
            raise RuntimeError("segfault, probably")

    r = quadratic_run(tmp_path, generations=3, evaluator=Boom()).run()
    assert r.accepted == 0
    records = [
        json.loads(line) for line in (tmp_path / "generations.jsonl").read_text().splitlines()
    ]
    assert all("failures" in rec["decision"]["rationale"] for rec in records)
