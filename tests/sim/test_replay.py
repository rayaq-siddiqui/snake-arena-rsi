import json
from pathlib import Path

import pytest

from arena.agents import make_policy
from arena.engine import GameConfig
from arena.sim.match import Match
from arena.sim.replay import build_replay, load_replay, resimulate, save_replay, verify_replay

CONFIG = GameConfig(width=16, height=16, score_target=5, max_ticks=1500)


def recorded(seed: int, policy: str = "random_safe") -> Match:
    m = Match([make_policy(policy) for _ in range(5)], seed, CONFIG, record=True)
    m.run()
    return m


@pytest.mark.parametrize("seed", range(20))
def test_replay_resimulates_exactly(seed: int, tmp_path: Path) -> None:
    m = recorded(seed, "random_uniform" if seed % 2 else "random_safe")
    path = tmp_path / f"m{seed}.json"
    save_replay(build_replay(m), path)
    replay = load_replay(path)
    assert verify_replay(replay)
    state, _ = resimulate(replay)
    assert state == m.state


def test_tampered_replay_fails_verification() -> None:
    replay = json.loads(json.dumps(build_replay(recorded(3))))
    for tick_actions in replay["actions"]:
        if tick_actions[0] is not None:
            tick_actions[0] = "LEFT" if tick_actions[0] != "LEFT" else "UP"
    assert not verify_replay(replay)


def test_unknown_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": 99}))
    with pytest.raises(ValueError):
        load_replay(path)


def test_unrecorded_match_cannot_build_a_replay() -> None:
    m = Match([make_policy("random_safe") for _ in range(5)], 1, CONFIG)
    with pytest.raises(ValueError):
        build_replay(m)
