import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from arena.cli import main
from arena.evolution.entrants import hand_set
from arena.evolution.evaluator import EvalSettings, Workers
from arena.evolution.map_elites import SnakeBehaviourEvaluator, heatmap_svg, snake_map_elites
from arena.rsi.map_elites import MapElitesConfig

TINY = EvalSettings(16, 16, 150)


def test_the_evaluator_is_deterministic_and_measures_behaviour() -> None:
    ev = SnakeBehaviourEvaluator("hunter", TINY, Workers(1))
    params = [hand_set("hunter"), {**hand_set("hunter"), "w_space": 0.0}]
    a = ev.evaluate(params, [1, 2, 3])
    assert a == ev.evaluate(params, [1, 2, 3])
    for e in a:
        assert len(e.scores) == 3 and all(s >= 0 for s in e.scores)
        distance, space = e.descriptors
        assert 0 < distance <= 32 and 0 < space <= 85


def test_a_snake_run_resumes_and_draws_its_heatmap(tmp_path: Path) -> None:
    config = MapElitesConfig(run_seed=1, batch=3, init_batches=1, dev_pairs=2, holdout_pairs=3)
    with Workers(1) as w:
        me = snake_map_elites("trapper", tmp_path, TINY, w, config)
        me.run(1)
        again = snake_map_elites("trapper", tmp_path, TINY, w, config)
        assert again.cells == me.cells and again.batches == 1
        again.run(2)
        assert again.history[-1]["episodes"] == 2 * 3 * 2
        holdout = again.holdout(hand_set("trapper"))
    assert holdout["baseline"]["params"] == hand_set("trapper")
    state = json.loads((tmp_path / "map_elites.json").read_text())
    root = ET.fromstring(heatmap_svg(state, holdout))
    assert root.tag.endswith("svg")
    assert len([r for r in root.iter() if r.tag.endswith("rect")]) >= 2 + len(state["cells"])


def test_cli_runs_a_tiny_map_elites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "me"
    args = ["map-elites", "survivor", "--profile", "quick", "--batches", "1", "--batch", "2"]
    args += ["--dev-pairs", "1", "--holdout-pairs", "1", "--workers", "1", "--out", str(out)]
    assert main(args) == 0
    assert "Holdout (1 seeds" in capsys.readouterr().out
    assert {p.name for p in out.iterdir()} >= {"map_elites.json", "holdout.json", "map_elites.svg"}
