import json

import pytest
from board_helpers import line, observe

from arena.agents import PERSONALITIES, make_policy
from arena.agents.base import Policy
from arena.agents.features import board_of
from arena.agents.opportunist import Opportunist
from arena.agents.params import PARAMS_DIR, load_params
from arena.agents.predictor import Predictor, enemy_layers
from arena.agents.registry import POLICIES
from arena.agents.scorer import ScoringPolicy
from arena.engine import GameConfig
from arena.sim.match import Match


@pytest.mark.parametrize("name", PERSONALITIES)
def test_each_personality_has_a_valid_params_file(name: str) -> None:
    cls = POLICIES[name]
    assert isinstance(cls, type) and issubclass(cls, ScoringPolicy)
    data = json.loads((PARAMS_DIR / f"{name}.json").read_text())
    assert data["name"] == name and data["version"] >= 1
    assert set(data["params"]) == set(cls.param_space.names)
    loaded = load_params(name, cls.param_space)
    policy = make_policy(name)
    assert isinstance(policy, ScoringPolicy)
    assert policy.params == dict(loaded.params) and policy.version == str(loaded.version)


@pytest.mark.parametrize("name", PERSONALITIES)
def test_each_personality_is_a_deterministic_policy(name: str) -> None:
    policy: Policy = make_policy(name)
    assert policy.name == name
    config = GameConfig(width=24, height=24, max_ticks=300, score_target=10**6)

    def play() -> tuple:
        lineup = [make_policy(name)] + [make_policy("random_safe") for _ in range(4)]
        result = Match(lineup, 11, config).run()
        return result.standings, result.kill_matrix, result.death_causes

    assert play() == play()


@pytest.mark.parametrize("name", PERSONALITIES)
def test_no_personality_takes_a_deadly_move_when_a_safe_one_exists(name: str) -> None:
    obs = observe({"s0": line((0, 5), "RIGHT"), "s1": line((0, 4), "UP")})
    assert make_policy(name).choose_action(obs) == "DOWN"


def test_hunter_heads_for_a_distant_enemy() -> None:
    obs = observe({"s0": line((5, 10), "LEFT"), "s1": line((30, 10), "RIGHT")}, size=40)
    assert make_policy("hunter").choose_action(obs) == "RIGHT"


def test_survivor_avoids_a_pocket() -> None:
    obs = observe({"s0": line((1, 0), "RIGHT"), "s1": line((0, 1), "DOWN")})
    assert make_policy("survivor").choose_action(obs) == "DOWN"


def test_opportunist_attacks_only_when_an_enemy_is_boxed_in() -> None:
    policy = make_policy("opportunist")
    assert isinstance(policy, Opportunist)
    open_board = board_of(observe({"s0": line((6, 4), "DOWN"), "s1": line((10, 10), "DOWN")}))
    assert not policy.attacking(open_board, "s0")
    assert policy.weights(open_board, "s0") is policy.cruise
    # s1 runs along the top wall with s2's body below it: one safe move left.
    boxed = board_of(
        observe(
            {
                "s0": line((6, 4), "DOWN"),
                "s1": line((4, 0), "LEFT"),
                "s2": line((5, 1), "LEFT"),
            }
        )
    )
    assert boxed.safe_moves["s1"] == ("RIGHT",)
    assert policy.attacking(boxed, "s0")
    assert policy.weights(boxed, "s0") is policy.attack


def test_predictor_spreads_enemy_heads_over_their_safe_moves() -> None:
    board = board_of(observe({"s0": line((10, 10), "DOWN"), "s1": line((3, 3), "LEFT")}))
    layers = enemy_layers(board, "s1", 2)
    assert {cell for cell, _ in layers[0]} == {(4, 3), (3, 2), (3, 4)}
    for layer in layers:
        assert sum(layer.values()) == pytest.approx(1.0)


def test_predictor_values_a_move_that_leaves_an_enemy_nowhere_to_go() -> None:
    # s1 runs right along the top wall toward s2's head; if s1 steps to (6, 0) and s0's head
    # is on (6, 1), s1 has no move left next tick.
    bodies = {"s0": line((6, 2), "DOWN"), "s1": line((5, 0), "LEFT"), "s2": line((7, 0), "RIGHT")}
    board = board_of(observe(bodies))
    predictor = make_policy("predictor")
    assert isinstance(predictor, Predictor)
    predictor._prepare(board, "s0")
    _, pressure_up = predictor._kills_and_pressure(board, "s0", (6, 1))
    _, pressure_right = predictor._kills_and_pressure(board, "s0", (7, 2))
    assert pressure_up > pressure_right
