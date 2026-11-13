from pathlib import Path

import pytest

from arena.cli import main
from arena.rsi.meta import META_SPACE, HillClimbTuning, InnerTask, inner_score, meta_run
from arena.rsi.types import Candidate

DEFAULTS = {p.name: p.default for p in META_SPACE}


def settings(**over: float) -> tuple[tuple[str, float], ...]:
    return tuple(sorted({**DEFAULTS, **over}.items()))


def test_inner_runs_are_deterministic_and_improve_on_the_start() -> None:
    task = InnerTask(settings(), seed=3, dim=3, generations=8, pairs=20)
    assert inner_score(task) == inner_score(task)
    start = InnerTask(settings(), seed=3, dim=3, generations=0, pairs=20)
    assert inner_score(task) > inner_score(start)


def test_paired_evaluation_uses_the_same_problems_and_caches() -> None:
    ev = HillClimbTuning(dim=3, generations=5, pairs=20)
    a = Candidate.make({**DEFAULTS, "sigma": 0.3}, None, 1, "test", "")
    b = Candidate.make(DEFAULTS, None, 0, "test", "")
    r = ev.evaluate(a, b, [1, 2])
    assert r.seeds == (1, 2) and len(ev._cache) == 4
    again = ev.evaluate(b, b, [1, 2])
    assert again.score_a == again.score_b == r.score_b and len(ev._cache) == 4


def test_meta_run_stays_in_bounds_and_resumes(tmp_path: Path) -> None:
    ev = HillClimbTuning(dim=3, generations=5, pairs=20)
    result = meta_run(str(tmp_path / "m"), 2, evaluator=ev, pairs=4, final_pairs=4).run()
    assert result.generations == 2
    for spec in META_SPACE:
        assert spec.low <= result.champion.params[spec.name] <= spec.high
    again = meta_run(str(tmp_path / "m"), 2, evaluator=ev, pairs=4, final_pairs=4).run()
    assert again.champion.id == result.champion.id


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["rsi-meta", "--generations", "1", "--inner-generations", "3", "--pairs", "3"]
    assert main([*args, "--workers", "1", "--out", str(tmp_path / "m")]) == 0
    out = capsys.readouterr().out
    assert "Settings kept: sigma" in out and "Run directory" in out
