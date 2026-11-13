import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pytest

from arena.rsi.map_elites import Axis, Evaluation, MapElites, MapElitesConfig
from arena.rsi.types import ParamSpec

SPACE = (
    ParamSpec("x", "float", 0.0, 1.0, 0.5),
    ParamSpec("y", "float", 0.0, 1.0, 0.5),
    ParamSpec("z", "float", -1.0, 1.0, 0.9),
)
AXES = (Axis("x", 0.0, 1.0, 4), Axis("y", 0.0, 1.0, 4))


class Toy:
    """Behaviour is (x, y); fitness peaks at z = 0 whatever the cell, plus seeded noise."""

    def __init__(self) -> None:
        self.seen: list[int] = []

    def evaluate(
        self, params: Sequence[Mapping[str, float]], seeds: Sequence[int]
    ) -> list[Evaluation]:
        self.seen += list(seeds)
        out = []
        for p in params:
            noise = [np.random.default_rng([s, 7]).normal(0, 0.05) for s in seeds]
            scores = tuple(-(p["z"] ** 2) + n for n in noise)
            out.append(Evaluation(scores, (p["x"], p["y"])))
        return out


def run(out: Path, batches: int, evaluator: Toy | None = None) -> MapElites:
    me = MapElites(
        out, SPACE, AXES, evaluator or Toy(), MapElitesConfig(run_seed=3, batch=8, dev_pairs=5)
    )
    me.run(batches)
    return me


def test_axis_bins_clip_to_the_edges() -> None:
    a = Axis("d", 0.0, 10.0, 5)
    assert [a.bin(v) for v in (-3, 0, 1.99, 2, 9.99, 10, 50)] == [0, 0, 0, 1, 4, 4, 4]


def test_the_archive_fills_the_grid_and_improves(tmp_path: Path) -> None:
    me = run(tmp_path, 12)
    assert len(me.cells) >= 14  # of 16
    for key, elite in me.cells.items():
        assert key == ",".join(map(str, me.cell_of(elite["descriptors"])))
    first, last = me.history[1], me.history[-1]
    assert last["qd_score"] > first["qd_score"] and last["episodes"] == 12 * 8 * 5
    assert all(h["best"] <= me.history[-1]["best"] for h in me.history)


def test_a_resumed_run_matches_an_uninterrupted_one(tmp_path: Path) -> None:
    straight = run(tmp_path / "a", 6)
    run(tmp_path / "b", 3)
    resumed = run(tmp_path / "b", 6)
    assert resumed.cells == straight.cells and resumed.history == straight.history


def test_a_different_run_in_the_same_directory_is_refused(tmp_path: Path) -> None:
    run(tmp_path, 1)
    with pytest.raises(ValueError, match="different MAP-Elites run"):
        MapElites(tmp_path, SPACE, AXES, Toy(), MapElitesConfig(run_seed=4, batch=8))


def test_the_search_never_sees_holdout_seeds(tmp_path: Path) -> None:
    toy = Toy()
    me = run(tmp_path, 4, toy)
    assert set(toy.seen) == set(me.dev_seeds)
    assert not set(me.dev_seeds) & set(me.holdout_seeds)
    report = me.holdout({"x": 0.5, "y": 0.5, "z": 0.9})
    assert set(toy.seen) - set(me.dev_seeds) == set(me.holdout_seeds)
    assert report["n"] == len(me.holdout_seeds) == 40
    assert len(report["elites"]) == len(me.cells)
    best = max(report["elites"], key=lambda e: e["holdout_fitness"])
    assert best["diff_vs_baseline"] > 0 and best["ci"][0] > 0
    assert json.loads((tmp_path / "holdout.json").read_text())["batches"] == 4


def test_stop_file_halts_between_batches(tmp_path: Path) -> None:
    run(tmp_path, 1)
    (tmp_path / "STOP").touch()
    assert run(tmp_path, 5).batches == 1
