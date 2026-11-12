from pathlib import Path

import pytest
from evo_helpers import AlwaysAccept, tiny_evolution

from arena.agents.scorer import ScoringPolicy
from arena.engine import GameConfig
from arena.evolution.entrants import hand_set
from arena.evolution.report import load_run
from arena.evolution.watch import run_roster
from arena.sim.match import simulate_match
from arena.viz.server import App

VIEW = GameConfig(width=16, height=16, score_target=3, max_ticks=300)


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("run")
    tiny_evolution(path, generations=3, rule=AlwaysAccept()).run()
    return path


def test_every_archived_champion_loads_and_plays(run_dir: Path) -> None:
    roster, first = run_roster(run_dir)
    assert first == "generation 3"
    _, views = load_run(run_dir)
    latest = {n: len(v.hall) for n, v in views.items()}
    assert max(latest.values()) > 2
    assert roster.lineups[first] == [f"{n}@v{k}" for n, k in latest.items()]
    assert sorted(roster.policies) == [
        f"{n}@v{v}" for n, k in latest.items() for v in range(1, k + 1)
    ]
    assert roster.labels["predictor@v2"][0] == "Predictor v2"
    for name in ("hunter", "predictor"):
        policy = roster.make(f"{name}@v1")
        assert isinstance(policy, ScoringPolicy) and policy.params == hand_set(name)
    app = App(VIEW, 7, first, None, roster)
    for policy in roster.policies:
        session = app.create({"policy": policy, "seed": 7})
        session.finish()
        assert session.finished
        assert session.meta()["snakes"][0]["label"].endswith(" s0")


def test_a_viewed_champion_plays_the_headless_game(run_dir: Path) -> None:
    roster, first = run_roster(run_dir, generation=2)
    session = App(VIEW, 11, first, None, roster).create({"policy": first, "seed": 11})
    meta = session.meta()
    _, views = load_run(run_dir)
    labels = [f"{n.title()} v{v.champion_at(2)[0]}" for n, v in views.items()]
    assert [s["label"] for s in meta["snakes"]] == labels
    assert meta["lineup"] == "generation 2"
    final = session.finish()
    config = GameConfig.from_dict({**VIEW.to_dict(), "num_snakes": 2})
    headless = simulate_match([roster.make(n) for n in roster.lineups[first]], 11, config)
    assert final["t"] == headless.ticks
    assert session.summary()["standings"] == [s.to_dict() for s in headless.standings]


def test_vs_generation_seats_evolved_and_earlier_versions(run_dir: Path) -> None:
    roster, first = run_roster(run_dir, vs_generation=0)
    assert first == "Hunter gen 3 vs gen 0"
    now = roster.lineups["generation 3"]
    assert roster.lineups[first] == [now[0], "hunter@v1", now[1]]
    assert roster.lineups["generation 0"] == ["hunter@v1", "predictor@v1"]
    session = App(VIEW, 3, first, None, roster).create({"policy": first, "seed": 3})
    labels = [s["label"] for s in session.meta()["snakes"]]
    assert labels[1] == "Hunter v1" and labels[0] != labels[1]
    assert session.config.num_snakes == 3
    with pytest.raises(ValueError, match="not in"):
        run_roster(run_dir, generation=9)
