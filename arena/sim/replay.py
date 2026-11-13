"""Replay files: everything needed to re-run a match without its policies (spec section 8)."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections import Counter
from pathlib import Path
from typing import Any

import arena
from arena.agents import Policy
from arena.engine import (
    SELF_INFLICTED,
    Event,
    GameConfig,
    GameState,
    Standing,
    new_game,
    rank,
    step,
)
from arena.sim.match import Match

SCHEMA_VERSION = 1


def policy_hash(policy: Policy) -> str:
    """Short sha256 of the policy class's source, so a replay names the exact code it ran."""
    try:
        source = inspect.getsource(type(policy))
    except (OSError, TypeError):
        source = f"{type(policy).__module__}.{type(policy).__qualname__}"
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def build_replay(match: Match) -> dict[str, Any]:
    if not match.record:
        raise ValueError("the match was not recorded; create it with record=True")
    config = match.config
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": arena.__version__,
        "config": config.to_dict(),
        "seed": match.seed,
        "policies": {
            sid: {"name": p.name, "version": p.version, "hash": policy_hash(p)}
            for sid, p in zip(config.snake_ids, match.policies, strict=True)
        },
        "initial_state": match.initial_state.to_dict(),
        "actions": match.actions,
        "events": [e.to_dict() for e in match.events],
        "final_standings": [s.to_dict() for s in rank(match.state.snakes)],
        "end_reason": match.state.end_reason,
    }


def save_replay(replay: dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(replay, separators=(",", ":")))


def load_replay(path: str | Path) -> dict[str, Any]:
    replay: dict[str, Any] = json.loads(Path(path).read_text())
    check_schema(replay)
    return replay


def check_schema(replay: dict[str, Any]) -> None:
    version = replay.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported replay schema_version {version!r}")


def resimulate(replay: dict[str, Any]) -> tuple[GameState, list[Event]]:
    """Re-run the stored actions through the engine. No policies are needed."""
    check_schema(replay)
    config = GameConfig.from_dict(replay["config"])
    state, events = new_game(config, int(replay["seed"]))
    if state.to_dict() != replay["initial_state"]:
        raise ValueError("replay initial state does not match the engine for this seed")
    ids = config.snake_ids
    for tick_actions in replay["actions"]:
        actions = {sid: a for sid, a in zip(ids, tick_actions, strict=True) if a is not None}
        state, tick_events = step(state, actions)
        events.extend(tick_events)
    return state, events


def scores_from_events(
    events: list[dict[str, Any]], self_death_penalty: int = 1
) -> dict[str, tuple[int, int, int]]:
    """(score, kills, deaths) per snake, counted from Kill and Death events alone.

    Score is kills minus ``self_death_penalty`` for every wall or own-body death.
    """
    kills = Counter(e["killer"] for e in events if e["type"] == "kill")
    deaths = Counter(e["victim"] for e in events if e["type"] == "death")
    own = Counter(
        e["victim"] for e in events if e["type"] == "death" and e["cause"] in SELF_INFLICTED
    )
    return {
        sid: (kills[sid] - self_death_penalty * own[sid], kills[sid], deaths[sid])
        for sid in kills.keys() | deaths.keys()
    }


def verify_replay(replay: dict[str, Any]) -> bool:
    """True when re-simulation reproduces the stored events and standings exactly, and the
    kills and deaths counted from the stored events match the stored standings."""
    try:
        state, events = resimulate(replay)
    except ValueError:
        return False
    stored = [e for e in replay["events"] if e["type"] != "action_fallback"]
    final = [Standing.from_dict(s) for s in replay["final_standings"]]
    if [e.to_dict() for e in events] != _upgraded(stored) or list(rank(state.snakes)) != final:
        return False
    counted = scores_from_events(replay["events"], state.config.self_death_penalty)
    return all(counted.get(s.snake, (0, 0, 0)) == (s.score, s.kills, s.deaths) for s in final)


def _upgraded(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stored events in today's format: replays saved before the self-death penalty
    have match-end standings without ``penalty`` and ``score``."""
    out = []
    for e in events:
        if e["type"] == "match_end":
            e = {**e, "standings": [Standing.from_dict(s).to_dict() for s in e["standings"]]}
        out.append(e)
    return out
