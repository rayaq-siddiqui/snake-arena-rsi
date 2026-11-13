import pytest

from arena.agents import RandomSafe, RandomUniform, make_policy
from arena.agents.base import Observation
from arena.engine import GameConfig
from arena.sim.match import Match, simulate_match

SMALL = GameConfig(width=20, height=20, score_target=5, max_ticks=3000)


def five(name: str = "random_safe") -> list:
    return [make_policy(name) for _ in range(5)]


def test_same_seed_same_result() -> None:
    a = simulate_match(five(), 3, SMALL)
    b = simulate_match(five(), 3, SMALL)
    assert a == b


def test_recorded_events_are_identical_across_runs() -> None:
    runs = []
    for _ in range(2):
        m = Match(five(), 11, SMALL, record=True)
        m.run()
        runs.append(([e.to_dict() for e in m.events], m.actions))
    assert runs[0] == runs[1]


def test_scores_equal_kill_events() -> None:
    m = Match(five(), 5, SMALL, record=True)
    result = m.run()
    for standing in result.standings:
        kills = sum(1 for e in m.events if e.kind == "kill" and e.killer == standing.snake)
        assert kills == standing.kills == sum(result.kill_matrix[standing.snake].values())


def test_match_ends_by_target_or_cap() -> None:
    result = simulate_match(five(), 1, SMALL)
    assert result.end_reason in {"score_target", "tick_cap"}
    if result.end_reason == "score_target":
        assert result.standings[0].kills >= SMALL.score_target
    else:
        assert result.ticks == SMALL.max_ticks


def careless_deaths(name: str) -> int:
    config = GameConfig(width=30, height=30, snake_length=5, max_ticks=2000)
    result = simulate_match(five(name), 2, config)
    return sum(c.get("wall", 0) + c.get("self", 0) for c in result.death_causes.values())


def test_random_safe_rarely_kills_itself_compared_with_random_uniform() -> None:
    safe, uniform = careless_deaths("random_safe"), careless_deaths("random_uniform")
    assert uniform > 100
    assert safe * 20 < uniform


class Exploding:
    name = "exploding"
    version = "1"

    def reset(self, seed: int) -> None:
        pass

    def choose_action(self, obs: Observation) -> str:
        raise RuntimeError("boom")


class Nonsense(Exploding):
    def choose_action(self, obs: Observation) -> str:
        return "NORTH-ISH"


def test_errors_and_invalid_actions_fall_back_and_the_match_continues() -> None:
    policies = [Exploding(), Nonsense(), RandomSafe(), RandomSafe(), RandomUniform()]
    m = Match(policies, 4, GameConfig(width=20, height=20, max_ticks=50), record=True)  # type: ignore[arg-type]
    result = m.run()
    reasons = {e.snake: e.reason for e in m.events if e.kind == "action_fallback"}
    assert reasons["s0"] == "error" and reasons["s1"] == "invalid"
    assert result.fallbacks > 0 and result.ticks == 50


def test_policy_count_must_match_config() -> None:
    with pytest.raises(ValueError):
        Match(five()[:4], 1, SMALL)
