from helpers import line, make_state

from arena.engine import GameConfig, MatchEnd, Spawn, new_game, rank, step
from arena.engine.spawn import find_spawn, is_valid_spawn, spawn_cells


def test_new_game_spawns_every_snake_without_overlap() -> None:
    for seed in range(50):
        state, events = new_game(GameConfig(), seed)
        cells = [c for s in state.snakes for c in s.body]
        assert len(cells) == len(set(cells)) == 25
        assert all(s.alive and len(s.body) == 5 and s.life_id == 1 for s in state.snakes)
        assert [e.snake for e in events if isinstance(e, Spawn)] == list(state.config.snake_ids)


def test_new_game_is_deterministic() -> None:
    assert new_game(GameConfig(), 7) == new_game(GameConfig(), 7)
    assert new_game(GameConfig(), 7)[0] != new_game(GameConfig(), 8)[0]


def test_spawn_respects_bounds_lookahead_and_clearance() -> None:
    config = GameConfig(width=20, height=20)
    assert spawn_cells((5, 5), "UP", 3) == ((5, 5), (5, 6), (5, 7))
    assert not is_valid_spawn((5, 1), "UP", config, set())  # faces the wall
    assert not is_valid_spawn((5, 17), "DOWN", config, set())
    assert is_valid_spawn((5, 5), "UP", config, set())
    assert not is_valid_spawn((5, 5), "UP", config, {(7, 9)})  # within clearance 2
    assert is_valid_spawn((5, 5), "UP", config, {(8, 9)})


def test_find_spawn_returns_none_when_full_without_crashing() -> None:
    config = GameConfig(width=10, height=10, snake_length=10, spawn_attempts=5)
    occupied = {(x, y) for x in range(10) for y in range(10) if (x + y) % 3 == 0}
    _, cells, heading = find_spawn(1, config, occupied)
    assert cells is None and heading is None


def test_respawn_after_exactly_the_delay_with_score_kept() -> None:
    config = GameConfig(width=20, height=20, snake_length=3)
    state = make_state(
        {"s0": line((0, 5), "RIGHT", 3)}, config=config, s0={"kills": 4, "life_id": 1}
    )
    state, _ = step(state, {"s0": "LEFT"})
    assert not state.snake("s0").alive and state.snake("s0").respawn_in == 10
    for _ in range(9):
        state, events = step(state, {})
        assert not state.snake("s0").alive
    state, events = step(state, {})
    s0 = state.snake("s0")
    assert state.tick == 11
    assert s0.alive and s0.life_id == 2 and s0.kills == 4 and s0.deaths == 1
    assert len(s0.body) == 3
    assert [e.kind for e in events] == ["spawn"]


def test_failed_respawn_retries_every_tick() -> None:
    config = GameConfig(width=10, height=10, snake_length=10, num_snakes=2, spawn_attempts=3)
    big = [(x, 5) for x in range(9, -1, -1)]  # a length-10 run can never fit with lookahead
    state = make_state({"s0": big}, config=config, s1={"respawn_in": 1})
    for _ in range(15):
        state, events = step(state, {})
        assert not any(e.kind == "spawn" for e in events)
        assert all(not s.alive and s.respawn_in == 0 for s in state.snakes if s.id == "s1")
    assert state.snake("s0").respawn_in == 0


def test_score_target_ends_the_match() -> None:
    config = GameConfig(width=10, height=10, snake_length=3, score_target=1)
    state = make_state(
        {"s0": line((2, 5), "LEFT", 3), "s1": line((3, 4), "DOWN", 3)}, config=config
    )
    state, events = step(state, {"s0": "RIGHT", "s1": "UP"})
    assert state.finished and state.end_reason == "score_target"
    end = events[-1]
    assert isinstance(end, MatchEnd) and end.standings[0].snake == "s1"


def test_tick_cap_ends_the_match_and_stepping_after_end_fails() -> None:
    config = GameConfig(width=10, height=10, snake_length=3, max_ticks=2)
    state = make_state({"s0": line((5, 5), "DOWN", 3)}, config=config)
    state, _ = step(state, {"s0": "UP"})
    assert not state.finished
    state, events = step(state, {"s0": "UP"})
    assert state.finished and state.end_reason == "tick_cap"
    assert isinstance(events[-1], MatchEnd)
    try:
        step(state, {})
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_ranking_tie_breakers_and_shared_rank() -> None:
    from arena.engine import SnakeState

    snakes = (
        SnakeState(id="s0", kills=3, deaths=2, alive_ticks=10),
        SnakeState(id="s1", kills=3, deaths=1, alive_ticks=5),
        SnakeState(id="s2", kills=1, deaths=0, alive_ticks=50),
        SnakeState(id="s3", kills=1, deaths=0, alive_ticks=50),
        SnakeState(id="s4", kills=1, deaths=0, alive_ticks=60),
    )
    got = [(s.snake, s.rank) for s in rank(snakes)]
    assert got == [("s1", 1), ("s0", 2), ("s4", 3), ("s2", 4), ("s3", 4)]


def test_ranking_uses_score_so_self_deaths_cost_places() -> None:
    from arena.engine import SnakeState

    snakes = (
        SnakeState(id="s0", kills=3, penalty=2),
        SnakeState(id="s1", kills=2),
        SnakeState(id="s2", kills=0, penalty=1),
    )
    standings = rank(snakes)
    assert [(s.snake, s.score) for s in standings] == [("s1", 2), ("s0", 1), ("s2", -1)]


def test_two_snakes_reaching_the_target_together_are_ranked_by_tie_breakers() -> None:
    config = GameConfig(width=10, height=10, snake_length=3, score_target=1)
    state = make_state(
        {
            "s0": line((2, 5), "LEFT", 3),
            "s1": line((3, 4), "DOWN", 3),
            "s2": line((6, 5), "LEFT", 3),
            "s3": line((7, 4), "DOWN", 3),
        },
        config=config,
        s1={"deaths": 2},
        s3={"deaths": 1},
    )
    state, events = step(state, {"s0": "RIGHT", "s1": "UP", "s2": "RIGHT", "s3": "UP"})
    assert state.finished and state.end_reason == "score_target"
    assert state.snake("s1").kills == 1 and state.snake("s3").kills == 1
    end = events[-1]
    assert isinstance(end, MatchEnd)
    assert [(s.snake, s.rank) for s in end.standings[:2]] == [("s3", 1), ("s1", 2)]
