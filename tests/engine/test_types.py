import json

import pytest

from arena.engine.types import (
    ActionFallback,
    Death,
    GameConfig,
    GameState,
    Kill,
    MatchEnd,
    SnakeState,
    Spawn,
    Standing,
    event_from_dict,
)


def roundtrip(data: object) -> object:
    return json.loads(json.dumps(data))


def test_config_defaults_match_spec() -> None:
    c = GameConfig()
    assert (c.width, c.height, c.num_snakes, c.snake_length) == (150, 150, 5, 10)
    assert (c.respawn_delay, c.score_target, c.max_ticks) == (10, 100, 100_000)
    assert c.snake_ids == ("s0", "s1", "s2", "s3", "s4")
    assert c.self_death_penalty == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"snake_length": 2},
        {"snake_length": 11},
        {"width": 9},
        {"num_snakes": 0},
        {"num_snakes": 9},
        {"respawn_delay": 0},
        {"score_target": 0},
        {"max_ticks": 0},
        {"self_death_penalty": -1},
    ],
)
def test_config_rejects_bad_values(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        GameConfig(**kwargs)


def test_config_roundtrip_and_unknown_keys() -> None:
    c = GameConfig(width=40, height=30, score_target=10)
    assert GameConfig.from_dict(roundtrip(c.to_dict())) == c  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        GameConfig.from_dict({"bogus": 1})


def test_configs_saved_before_the_penalty_replay_without_it() -> None:
    old = GameConfig(width=40, height=30).to_dict()
    del old["self_death_penalty"]
    assert GameConfig.from_dict(old).self_death_penalty == 0


def test_state_roundtrip() -> None:
    snake = SnakeState(id="s0", body=((3, 3), (3, 4), (3, 5)), heading="UP", alive=True)
    state = GameState(config=GameConfig(), snakes=(snake, SnakeState(id="s1")), rng_state=99)
    assert GameState.from_dict(roundtrip(state.to_dict())) == state  # type: ignore[arg-type]


def test_events_roundtrip() -> None:
    events = [
        Death(tick=3, victim="s1", killer="s0", cause="body", cell=(4, 4)),
        Kill(tick=3, killer="s0", victim="s1"),
        Spawn(tick=0, snake="s0", life_id=1, cells=((1, 1), (1, 2)), heading="UP"),
        ActionFallback(tick=2, snake="s3", reason="error"),
        MatchEnd(tick=9, reason="tick_cap", standings=(Standing("s0", 1, 2, 0, 9, 1),)),
    ]
    for e in events:
        assert event_from_dict(roundtrip(e.to_dict())) == e  # type: ignore[arg-type]
    assert events[-1].to_dict()["standings"][0]["score"] == 1
