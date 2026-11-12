"""Randomised invariant checks over many seeds and thousands of ticks (plan step 1.6)."""

from hypothesis import given, settings
from hypothesis import strategies as st

from arena.agents import make_policy
from arena.engine import DELTAS, OPPOSITE, GameConfig, Kill, Spawn
from arena.sim.match import Match


def check_shape(state) -> None:
    config = state.config
    occupied = []
    for s in state.snakes:
        if not s.alive:
            assert s.body == ()
            continue
        assert len(s.body) == config.snake_length
        assert len(set(s.body)) == len(s.body)
        for x, y in s.body:
            assert 0 <= x < config.width and 0 <= y < config.height
        for (ax, ay), (bx, by) in zip(s.body, s.body[1:], strict=False):
            assert abs(ax - bx) + abs(ay - by) == 1
        occupied.extend(s.body)
    assert len(occupied) == len(set(occupied)), "two living snakes overlap"


def run_and_check(seed: int, policy: str, config: GameConfig) -> None:
    match = Match([make_policy(policy) for _ in range(config.num_snakes)], seed, config)
    kills = {sid: 0 for sid in config.snake_ids}
    while not match.finished:
        before = {s.id: s for s in match.state.snakes}
        events = match.advance()
        spawned = {e.snake for e in events if isinstance(e, Spawn)}
        for e in events:
            if isinstance(e, Kill):
                kills[e.killer] += 1
        check_shape(match.state)
        for s in match.state.snakes:
            old = before[s.id]
            if s.alive and old.alive and s.id not in spawned:
                (hx, hy), (ox, oy) = s.body[0], old.body[0]
                assert abs(hx - ox) + abs(hy - oy) == 1
                assert s.heading != OPPOSITE[old.heading]  # type: ignore[index]
                assert DELTAS[s.heading] == (hx - ox, hy - oy)  # type: ignore[index]
                assert s.body[1:] == old.body[:-1]
            assert s.kills == kills[s.id]
            assert s.kills >= old.kills and s.deaths >= old.deaths


@settings(max_examples=200, deadline=None)
@given(seed=st.integers(0, 2**32), policy=st.sampled_from(["random_uniform", "random_safe"]))
def test_invariants_hold_on_small_crowded_boards(seed: int, policy: str) -> None:
    run_and_check(seed, policy, GameConfig(width=12, height=12, max_ticks=2000, score_target=10**6))


def test_invariants_hold_on_the_default_board() -> None:
    for seed in range(4):
        run_and_check(seed, "random_safe", GameConfig(max_ticks=2000))


def test_invariants_hold_for_other_lengths_and_counts() -> None:
    for length, count in [(3, 2), (7, 8), (10, 5)]:
        config = GameConfig(width=20, height=20, snake_length=length, num_snakes=count)
        run_and_check(
            length, "random_uniform", GameConfig(**{**config.to_dict(), "max_ticks": 800})
        )
