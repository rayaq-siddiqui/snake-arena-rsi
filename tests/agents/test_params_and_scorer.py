import json
from pathlib import Path

import pytest
from board_helpers import line, observe

from arena.agents.params import Param, ParamSet, ParamSpace, load_params, save_params
from arena.agents.scorer import COMMON_PARAMS, ScoringPolicy, feature_weights, weight

SPACE = ParamSpace(
    (
        Param("w_space", 1.0, -10.0, 10.0),
        Param("space_cap", 60, 10, 200, "int"),
    )
)


def test_validate_fills_defaults_and_keeps_types() -> None:
    assert SPACE.validate({}) == {"w_space": 1.0, "space_cap": 60}
    got = SPACE.validate({"space_cap": 80.0, "w_space": 3})
    assert got == {"w_space": 3.0, "space_cap": 80}
    assert isinstance(got["space_cap"], int) and isinstance(got["w_space"], float)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"w_bogus": 1.0}, "unknown parameters: w_bogus"),
        ({"w_space": 11.0}, "outside"),
        ({"space_cap": 9}, "outside"),
        ({"space_cap": 61.5}, "integer"),
        ({"w_space": "2"}, "number"),
        ({"w_space": True}, "number"),
    ],
)
def test_bad_values_are_rejected_with_a_clear_error(values: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SPACE.validate(values)


def test_space_rejects_bad_declarations() -> None:
    with pytest.raises(ValueError, match="default"):
        Param("x", 5.0, 0.0, 1.0)
    with pytest.raises(ValueError, match="duplicate"):
        ParamSpace((Param("x", 0.0, 0.0, 1.0), Param("x", 0.0, 0.0, 1.0)))
    with pytest.raises(ValueError, match="unknown feature"):
        weight("not_a_feature", 0.0)


def test_params_round_trip_through_json(tmp_path: Path) -> None:
    path = tmp_path / "toy.json"
    save_params(ParamSet("toy", 3, {"w_space": 2.5}), SPACE, path)
    loaded = load_params("toy", SPACE, path)
    assert loaded == ParamSet("toy", 3, {"w_space": 2.5, "space_cap": 60})


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"name": "other", "version": 1, "params": {}}, "expected 'toy'"),
        ({"name": "toy", "version": 0, "params": {}}, "version"),
        ({"name": "toy", "version": 1, "params": {"w_space": 99}}, "outside"),
    ],
)
def test_bad_params_files_are_rejected(tmp_path: Path, data: dict, message: str) -> None:
    path = tmp_path / "toy.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message):
        load_params("toy", SPACE, path)


def test_feature_weights_keeps_only_non_zero_feature_weights() -> None:
    params = {"w_space": 2.0, "w_wall_distance": 0.0, "space_cap": 60, "a_space": 5.0}
    assert feature_weights(params) == {"space": 2.0}
    assert feature_weights(params, "a_") == {"space": 5.0}


class Toy(ScoringPolicy):
    name = "toy"
    param_space = ParamSpace((*COMMON_PARAMS, weight("wall_distance", 0.0)))


def toy(**params: float) -> Toy:
    return Toy(ParamSet("toy", 1, params))


def test_scorer_never_picks_a_deadly_move_when_a_safe_one_exists() -> None:
    obs = observe({"s0": line((0, 5), "RIGHT"), "s1": line((0, 4), "UP")})
    assert toy(random_tiebreak=0).choose_action(obs) == "DOWN"


def test_ties_break_in_fixed_direction_order_without_random_tiebreaks() -> None:
    obs = observe({"s0": line((10, 10), "DOWN")})
    assert toy(random_tiebreak=0).choose_action(obs) == "UP"
    obs = observe({"s0": line((10, 10), "UP")})
    assert toy(random_tiebreak=0).choose_action(obs) == "RIGHT"


def test_weights_steer_the_choice() -> None:
    obs = observe({"s0": line((3, 10), "DOWN")})
    assert toy(random_tiebreak=0, w_wall_distance=5.0).choose_action(obs) == "RIGHT"
    assert toy(random_tiebreak=0, w_wall_distance=-5.0).choose_action(obs) == "LEFT"


def test_random_tiebreaks_are_seeded() -> None:
    obs = observe({"s0": line((10, 10), "DOWN")})

    def picks(seed: int) -> list[str]:
        policy = toy(random_tiebreak=1)
        policy.reset(seed)
        return [policy.choose_action(obs) for _ in range(30)]

    assert picks(1) == picks(1)
    assert set(picks(1)) == {"UP", "RIGHT", "LEFT"}
