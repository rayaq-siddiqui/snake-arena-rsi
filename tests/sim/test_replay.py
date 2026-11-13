import json
from pathlib import Path

import pytest

from arena.agents import make_policy
from arena.engine import GameConfig
from arena.sim.match import Match
from arena.sim.replay import (
    build_replay,
    load_replay,
    policy_hash,
    resimulate,
    save_replay,
    scores_from_events,
    verify_replay,
)

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


def test_replay_names_each_snakes_policy_with_a_source_hash() -> None:
    replay = build_replay(recorded(2))
    assert list(replay["policies"]) == ["s0", "s1", "s2", "s3", "s4"]
    entry = replay["policies"]["s0"]
    assert entry["name"] == "random_safe"
    assert entry["hash"] == policy_hash(make_policy("random_safe"))
    assert policy_hash(make_policy("random_safe")) != policy_hash(make_policy("random_uniform"))


@pytest.mark.parametrize("seed", range(10))
def test_scores_recomputed_from_events_match_standings(seed: int) -> None:
    replay = build_replay(recorded(seed))
    counted = scores_from_events(replay["events"], CONFIG.self_death_penalty)
    for s in replay["final_standings"]:
        assert counted.get(s["snake"], (0, 0, 0)) == (s["score"], s["kills"], s["deaths"])


def test_dropping_a_kill_event_fails_verification() -> None:
    replay = json.loads(json.dumps(build_replay(recorded(0))))
    kills = [i for i, e in enumerate(replay["events"]) if e["type"] == "kill"]
    assert kills
    del replay["events"][kills[0]]
    assert not verify_replay(replay)


def test_replays_saved_before_the_self_death_penalty_still_verify() -> None:
    config = GameConfig(width=16, height=16, score_target=5, max_ticks=1500, self_death_penalty=0)
    m = Match([make_policy("random_uniform") for _ in range(5)], 3, config, record=True)
    m.run()
    replay = json.loads(json.dumps(build_replay(m)))
    del replay["config"]["self_death_penalty"]
    for s in replay["final_standings"]:
        del s["penalty"], s["score"]
    for e in replay["events"]:
        if e["type"] == "match_end":
            for s in e["standings"]:
                del s["penalty"], s["score"]
    assert any(e["type"] == "death" and e["cause"] in ("wall", "self") for e in replay["events"])
    assert verify_replay(replay)
    replay["config"]["self_death_penalty"] = 1
    assert not verify_replay(replay)
