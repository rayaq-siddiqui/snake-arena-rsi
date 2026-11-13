"""Golden tests: one hand-drawn board per collision rule (phase 1 spec, section 11)."""

from helpers import line, make_state

from arena.engine import Death, GameConfig, Kill, step


def deaths(events: list) -> dict[str, tuple[str, str | None]]:
    return {e.victim: (e.cause, e.killer) for e in events if isinstance(e, Death)}


def kills(events: list) -> list[tuple[str, str]]:
    return sorted((e.killer, e.victim) for e in events if isinstance(e, Kill))


def scores(state) -> dict[str, int]:
    return {s.id: s.score for s in state.snakes}


def test_straight_move_advances_and_keeps_length() -> None:
    state = make_state({"s0": line((5, 5), "DOWN", 5)})
    nxt, events = step(state, {"s0": "UP"})
    s0 = nxt.snake("s0")
    assert s0.body == ((5, 4), (5, 5), (5, 6), (5, 7), (5, 8))
    assert s0.heading == "UP" and not deaths(events)


def test_reversal_continues_straight() -> None:
    state = make_state({"s0": line((5, 5), "DOWN", 5)})
    nxt, _ = step(state, {"s0": "DOWN"})
    assert nxt.snake("s0").body[0] == (5, 4)


def test_invalid_action_continues_straight_and_is_logged() -> None:
    state = make_state({"s0": line((5, 5), "DOWN", 5)})
    nxt, events = step(state, {"s0": "SIDEWAYS"})
    assert nxt.snake("s0").body[0] == (5, 4)
    assert [e.kind for e in events] == ["action_fallback"]


def test_wall_kills_without_credit_and_costs_a_point() -> None:
    state = make_state({"s0": line((0, 5), "RIGHT", 5)})
    nxt, events = step(state, {"s0": "LEFT"})
    assert deaths(events) == {"s0": ("wall", None)}
    assert not nxt.snake("s0").alive and nxt.snake("s0").deaths == 1
    assert kills(events) == []
    assert nxt.snake("s0").kills == 0 and scores(nxt)["s0"] == -1


def test_own_body_kills_without_credit_and_costs_a_point() -> None:
    body = [(2, 2), (3, 2), (3, 3), (2, 3), (1, 3)]
    nxt, events = step(make_state({"s0": body}), {"s0": "DOWN"})
    assert deaths(events) == {"s0": ("self", None)}
    assert scores(nxt)["s0"] == -1


def test_self_death_penalty_is_configurable_and_survives_respawn() -> None:
    config = GameConfig(width=10, height=10, snake_length=5, self_death_penalty=0)
    state = make_state({"s0": line((0, 5), "RIGHT", 5)}, config=config)
    nxt, _ = step(state, {"s0": "LEFT"})
    assert scores(nxt)["s0"] == 0

    config = GameConfig(width=10, height=10, snake_length=5, self_death_penalty=3)
    state, _ = step(make_state({"s0": line((0, 5), "RIGHT", 5)}, config=config), {"s0": "LEFT"})
    for _ in range(config.respawn_delay):
        state, _ = step(state, {})
    s0 = state.snake("s0")
    assert s0.alive and s0.life_id == 1 and s0.score == -3 and s0.penalty == 3


def test_own_vacated_tail_is_safe() -> None:
    body = [(2, 2), (3, 2), (3, 3), (2, 3)]
    nxt, events = step(make_state({"s0": body}), {"s0": "DOWN"})
    assert not deaths(events)
    assert nxt.snake("s0").body == ((2, 3), (2, 2), (3, 2), (3, 3))


def test_hitting_another_body_credits_its_owner() -> None:
    state = make_state({"s0": line((2, 5), "LEFT", 3), "s1": line((3, 3), "DOWN", 5)})
    nxt, events = step(state, {"s0": "RIGHT", "s1": "UP"})
    assert deaths(events) == {"s0": ("body", "s1")}
    assert kills(events) == [("s1", "s0")]
    assert scores(nxt)["s1"] == 1 and nxt.snake("s1").alive


def test_owner_is_credited_even_if_it_dies_the_same_tick() -> None:
    state = make_state({"s0": line((2, 5), "LEFT", 3), "s1": line((3, 0), "DOWN", 7)})
    nxt, events = step(state, {"s0": "RIGHT", "s1": "UP"})
    assert deaths(events) == {"s0": ("body", "s1"), "s1": ("wall", None)}
    assert nxt.snake("s1").kills == 1 and scores(nxt)["s1"] == 0
    assert not nxt.snake("s1").alive


def test_one_owner_earns_a_point_per_victim() -> None:
    state = make_state(
        {
            "s0": line((2, 5), "LEFT", 3),
            "s1": line((3, 3), "DOWN", 5),
            "s2": line((4, 6), "RIGHT", 3),
        }
    )
    nxt, events = step(state, {"s0": "RIGHT", "s1": "UP", "s2": "LEFT"})
    assert deaths(events) == {"s0": ("body", "s1"), "s2": ("body", "s1")}
    assert scores(nxt)["s1"] == 2


def test_head_on_kills_both_without_credit() -> None:
    state = make_state({"s0": line((4, 5), "LEFT", 3), "s1": line((6, 5), "RIGHT", 3)})
    nxt, events = step(state, {"s0": "RIGHT", "s1": "LEFT"})
    assert deaths(events) == {"s0": ("head_on", None), "s1": ("head_on", None)}
    assert kills(events) == [] and set(scores(nxt).values()) == {0}


def test_three_way_head_on() -> None:
    state = make_state(
        {
            "s0": line((4, 5), "LEFT", 3),
            "s1": line((6, 5), "RIGHT", 3),
            "s2": line((5, 6), "DOWN", 3),
        }
    )
    _, events = step(state, {"s0": "RIGHT", "s1": "LEFT", "s2": "UP"})
    assert deaths(events) == {s: ("head_on", None) for s in ("s0", "s1", "s2")}


def test_head_swap_kills_both_without_credit() -> None:
    state = make_state({"s0": line((5, 5), "LEFT", 3), "s1": line((6, 5), "RIGHT", 3)})
    _nxt, events = step(state, {"s0": "RIGHT", "s1": "LEFT"})
    assert deaths(events) == {"s0": ("head_swap", None), "s1": ("head_swap", None)}
    assert kills(events) == []


def test_following_another_tail_is_safe() -> None:
    state = make_state({"s0": line((5, 5), "DOWN", 3), "s1": line((5, 2), "DOWN", 3)})
    nxt, events = step(state, {"s0": "UP", "s1": "UP"})
    assert not deaths(events)
    assert nxt.snake("s0").body[0] == (5, 4)


def test_two_heads_racing_into_a_vacated_tail_is_a_head_on() -> None:
    state = make_state(
        {
            "s0": line((4, 5), "LEFT", 3),
            "s1": line((5, 3), "UP", 3),
            "s2": line((6, 5), "RIGHT", 3),
        }
    )
    _, events = step(state, {"s0": "RIGHT", "s1": "UP", "s2": "LEFT"})
    assert deaths(events) == {"s0": ("head_on", None), "s2": ("head_on", None)}


def test_head_on_inside_a_body_cell_credits_the_body_owner() -> None:
    state = make_state(
        {
            "s0": line((4, 5), "LEFT", 3),
            "s1": line((6, 5), "RIGHT", 3),
            "s2": line((5, 6), "UP", 4),
        }
    )
    nxt, events = step(state, {"s0": "RIGHT", "s1": "LEFT", "s2": "DOWN"})
    assert deaths(events) == {"s0": ("body", "s2"), "s1": ("body", "s2")}
    assert scores(nxt)["s2"] == 2


def test_results_do_not_depend_on_snake_order() -> None:
    bodies = {
        "s0": line((2, 5), "LEFT", 3),
        "s1": line((3, 3), "DOWN", 5),
        "s2": line((4, 6), "RIGHT", 3),
        "s3": line((7, 1), "RIGHT", 3),
        "s4": line((8, 8), "UP", 3),
    }
    actions = {"s0": "RIGHT", "s1": "UP", "s2": "LEFT", "s3": "UP", "s4": "LEFT"}
    state = make_state(bodies)
    reordered = state.__class__(
        config=state.config, snakes=tuple(reversed(state.snakes)), rng_state=state.rng_state
    )
    a, ea = step(state, actions)
    b, eb = step(reordered, actions)
    assert deaths(ea) == deaths(eb)
    assert scores(a) == scores(b)
    assert {s.id: s.body for s in a.snakes} == {s.id: s.body for s in b.snakes}


def test_config_is_honoured_for_custom_lengths() -> None:
    config = GameConfig(width=12, height=12, snake_length=3)
    state = make_state({"s0": line((5, 5), "DOWN", 3)}, config=config)
    nxt, _ = step(state, {"s0": "LEFT"})
    assert len(nxt.snake("s0").body) == 3
