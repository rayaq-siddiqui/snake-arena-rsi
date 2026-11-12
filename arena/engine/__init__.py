"""Pure, deterministic game rules. No I/O, no rendering, no global randomness."""

from arena.engine.step import new_game, rank, resolve_direction, step
from arena.engine.types import (
    DELTAS,
    DIRECTIONS,
    OPPOSITE,
    ActionFallback,
    Cell,
    Death,
    Direction,
    Event,
    GameConfig,
    GameState,
    Kill,
    MatchEnd,
    SnakeId,
    SnakeState,
    Spawn,
    Standing,
)

__all__ = [
    "DELTAS",
    "DIRECTIONS",
    "OPPOSITE",
    "ActionFallback",
    "Cell",
    "Death",
    "Direction",
    "Event",
    "GameConfig",
    "GameState",
    "Kill",
    "MatchEnd",
    "SnakeId",
    "SnakeState",
    "Spawn",
    "Standing",
    "new_game",
    "rank",
    "resolve_direction",
    "step",
]
