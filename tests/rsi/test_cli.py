from pathlib import Path

import pytest

from arena.cli import main


def test_rsi_demo_writes_a_run_directory_and_resumes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "run"
    args = ["rsi-demo", "--problem", "quadratic", "--dim", "2", "--out", str(out)]
    assert main([*args, "--generations", "4"]) == 0
    for name in ("config.json", "seeds.json", "generations.jsonl", "champion.json", "report.md"):
        assert (out / name).exists(), name
    assert (out / "archive").is_dir()
    assert main([*args, "--generations", "6"]) == 0
    assert len((out / "generations.jsonl").read_text().splitlines()) == 6
    text = capsys.readouterr().out
    assert "gen   6" in text and "True score" in text
