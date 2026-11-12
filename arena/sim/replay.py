"""Replay files: everything needed to re-run a match without its policies (spec section 8)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import arena
from arena.engine import Event, GameConfig, GameState, new_game, rank, step
from arena.sim.match import Match

SCHEMA_VERSION = 1


def build_replay(match: Match) -> dict[str, Any]:
    if not match.record:
        raise ValueError("the match was not recorded; create it with record=True")
    config = match.config
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": arena.__version__,
        "config": config.to_dict(),
        "seed": match.seed,
        "policies": [
            {"snake": sid, "name": p.name, "version": p.version}
            for sid, p in zip(config.snake_ids, match.policies, strict=True)
        ],
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


def verify_replay(replay: dict[str, Any]) -> bool:
    """True when re-simulation reproduces the stored engine events and standings exactly."""
    try:
        state, events = resimulate(replay)
    except ValueError:
        return False
    stored = [e for e in replay["events"] if e["type"] != "action_fallback"]
    standings = [s.to_dict() for s in rank(state.snakes)]
    return [e.to_dict() for e in events] == stored and standings == replay["final_standings"]
