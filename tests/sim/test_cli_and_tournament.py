from pathlib import Path

import pytest

from arena.cli import main
from arena.engine import GameConfig
from arena.sim.replay import load_replay, verify_replay
from arena.sim.tournament import run_matches, summarise, summary_csv

SMALL = ["--width", "16", "--height", "16", "--max-ticks", "800", "--target", "5"]


def test_run_match_prints_standings(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run-match", "--seed", "3", *SMALL]) == 0
    out = capsys.readouterr().out
    assert "Match seed 3" in out and "rank" in out and "s0" in out


def test_run_match_writes_a_verifiable_replay(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    assert main(["run-match", "--seed", "4", *SMALL, "--replay", str(path)]) == 0
    assert verify_replay(load_replay(path))


def test_run_match_json_output_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    main(["run-match", "--seed", "5", *SMALL, "--json"])
    first = capsys.readouterr().out
    main(["run-match", "--seed", "5", *SMALL, "--json"])
    assert capsys.readouterr().out == first


def test_bad_policy_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        main(["run-match", "--policy", "nope"])


def test_tournament_outputs_do_not_depend_on_workers(tmp_path: Path) -> None:
    for workers in (1, 3):
        args = ["run-tournament", "--matches", "6", *SMALL, "--workers", str(workers)]
        assert main([*args, "--out", str(tmp_path / f"w{workers}")]) == 0
    for name in ("matches.jsonl", "summary.csv", "kill_matrix.csv"):
        assert (tmp_path / "w1" / name).read_bytes() == (tmp_path / "w3" / name).read_bytes()


def test_summary_counts_add_up() -> None:
    config = GameConfig(width=16, height=16, max_ticks=500, score_target=3)
    results = list(run_matches(["random_safe"] * 5, range(5), config))
    summaries = summarise(results)
    assert sum(s.wins for s in summaries) <= 5
    assert all(s.matches == 5 for s in summaries)
    assert summary_csv(summaries).startswith("snake,policy,matches,wins")


def test_bench_reports_rates(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bench", "--ticks", "500", "--width", "20", "--height", "20"]) == 0
    out = capsys.readouterr().out
    assert "engine only" in out and "kills per 1,000 ticks" in out


def test_bench_measures_total_throughput_over_workers(capsys: pytest.CaptureFixture[str]) -> None:
    args = ["bench", "--ticks", "300", "--width", "20", "--height", "20", "--workers", "2"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "2 worker processes, 4 games of 300 ticks each" in out
    assert "engine only, total:" in out and "match (random_safe), total:" in out


def test_bench_times_every_personality(capsys: pytest.CaptureFixture[str]) -> None:
    main(["bench", "--policies", "all", "--ticks", "60", "--width", "30", "--height", "30"])
    out = capsys.readouterr().out
    for name in ("hunter", "survivor", "trapper", "predictor", "opportunist"):
        assert name in out
    assert "median ms" in out


def test_personalities_lineup_expands_in_seat_order(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run-match", *SMALL, "--policy", "personalities", "--max-ticks", "50"]) == 0
    out = capsys.readouterr().out
    assert "hunter" in out and "opportunist" in out


def test_check_personalities_writes_a_report(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    args = ["check-personalities", "--matches", "2", "--ticks", "200", "--width", "20"]
    main([*args, "--height", "20", "--out", str(out)])
    text = out.read_text()
    assert "## Acceptance" in text and text.count("PASS") + text.count("FAIL") >= 13
