import json
from pathlib import Path

import pytest

from arena.agents import hunter
from arena.evolution.code_proposer import (
    build_prompt,
    dev_history,
    propose_code,
    static_checks,
)
from arena.rsi.llm import Reply

SOURCE = Path(hunter.__file__).read_text()
GOOD = SOURCE.replace('weight("cut_off", 12.0)', 'weight("cut_off", 18.0)')


def fake(text: str, calls: list[tuple[str, str]] | None = None):
    def complete(system: str, prompt: str) -> Reply:
        if calls is not None:
            calls.append((system, prompt))
        return Reply(text, 1000, 500)

    return complete


def test_good_proposal_is_stored_as_a_patch_and_never_applied(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    p = propose_code(
        "hunter", tmp_path, complete=fake(f"Cut off harder.\n```python\n{GOOD}```", calls)
    )
    assert p.passed and p.path == tmp_path / "hunter" / "001"
    diff = (p.path / "patch.diff").read_text()
    assert '-            weight("cut_off", 12.0),' in diff
    assert '+            weight("cut_off", 18.0),' in diff
    assert Path(hunter.__file__).read_text() == SOURCE
    assert "Cut off harder." in (p.path / "REVIEW.md").read_text()
    audit = json.loads((p.path / "audit.json").read_text())
    assert audit["input_tokens"] == 1000 and audit["dollars"] == pytest.approx(p.dollars)
    assert "class Hunter" in calls[0][1]
    assert (
        propose_code("hunter", tmp_path, complete=fake(f"```python\n{GOOD}```")).path.name == "002"
    )


@pytest.mark.parametrize(
    ("snippet", "check"),
    [
        ("import os\n", "imports"),
        ("from subprocess import run\n", "imports"),
        ("X = open('/etc/passwd')\n", "names"),
        ("X = eval('1')\n", "names"),
        ("X = ().__class__.__subclasses__()\n", "names"),
        ("def broken(:\n", "parses"),
    ],
)
def test_static_checks_flag_unsafe_or_broken_code(snippet: str, check: str) -> None:
    checks = static_checks(GOOD + snippet, "hunter")
    assert checks[check] != "ok"


def test_static_checks_require_the_policy_name() -> None:
    assert static_checks(GOOD, "hunter")["interface"] == "ok"
    assert (
        static_checks(GOOD.replace('name = "hunter"', 'name = "x"'), "hunter")["interface"] != "ok"
    )


def test_failed_proposal_is_marked_and_unusable_reply_kept_for_audit(tmp_path: Path) -> None:
    bad = propose_code("hunter", tmp_path, complete=fake(f"```python\nimport os\n{GOOD}```"))
    assert not bad.passed and "FAILED" in (bad.path / "REVIEW.md").read_text()
    none = propose_code("hunter", tmp_path, complete=fake("no code here"))
    assert not none.passed and not (none.path / "patch.diff").exists()
    assert json.loads((none.path / "audit.json").read_text())["reply"] == "no code here"


def test_prompt_shows_dev_results_but_no_holdout_numbers_or_seeds(tmp_path: Path) -> None:
    lineage = tmp_path / "lineages" / "hunter"
    lineage.mkdir(parents=True)
    rec = {
        "generation": 1,
        "chosen": "c1",
        "decision": {
            "accept": True,
            "stats": {
                "dev": {"diff": 0.25, "n": 40, "seeds": [777001]},
                "holdout": {"diff": 0.987654, "seeds": [999001]},
            },
        },
        "feedback": [{"candidate": {"id": "c1", "note": "w_cut_off 12->18"}}],
    }
    (lineage / "generations.jsonl").write_text(json.dumps(rec) + "\n")
    history = dev_history(tmp_path, "hunter")
    assert history == [
        {
            "generation": 1,
            "change": "w_cut_off 12->18",
            "dev_diff": 0.25,
            "dev_n": 40,
            "accepted": True,
        }
    ]
    prompt = build_prompt("hunter", SOURCE, {"w_cut_off": 12.0}, history)
    assert "0.25" in prompt and "w_cut_off 12->18" in prompt
    for hidden in ("0.987654", "999001", "777001", "holdout"):
        assert hidden not in prompt


def test_unknown_snake_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        propose_code("../engine/step", tmp_path, complete=fake(""))


def test_cli_stores_proposals_within_the_dollar_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from arena import cli
    from arena.evolution import code_proposer

    monkeypatch.setattr(
        code_proposer, "anthropic_complete", lambda *a, **k: fake(f"```python\n{GOOD}```")
    )
    argv = ["propose-code", "hunter", "--out", str(tmp_path), "--count", "5"]
    assert cli.main([*argv, "--max-llm-dollars", "0.015"]) == 0
    out = capsys.readouterr().out
    assert "Stopped" in out and "Nothing was applied" in out
    assert sorted(p.name for p in (tmp_path / "hunter").iterdir()) == ["001", "002"]
