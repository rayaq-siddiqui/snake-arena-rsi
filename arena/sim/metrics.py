"""Behaviour metrics sampled during a match (phase 2 spec, section 3).

The same measurement is used for every snake whatever its policy, so the numbers compare
personalities fairly: Manhattan distance from the head to the nearest enemy head
(aggression) and cells reachable from the head (caution), capped and radius-bounded.
"""

from __future__ import annotations

from dataclasses import dataclass

from arena.agents.base import Observation, legal_moves, next_cell, snake_views
from arena.agents.features import board_of, flood_fill, manhattan
from arena.engine import GameState

SPACE_CAP = 200
SPACE_RADIUS = 15


@dataclass
class Behaviour:
    """Running sums for one snake; ``mean_*`` are None until something was sampled."""

    distance_sum: int = 0
    distance_samples: int = 0
    space_sum: int = 0
    space_samples: int = 0

    def add(self, other: Behaviour) -> None:
        self.distance_sum += other.distance_sum
        self.distance_samples += other.distance_samples
        self.space_sum += other.space_sum
        self.space_samples += other.space_samples

    @property
    def mean_enemy_distance(self) -> float | None:
        return self.distance_sum / self.distance_samples if self.distance_samples else None

    @property
    def mean_space(self) -> float | None:
        return self.space_sum / self.space_samples if self.space_samples else None

    def to_dict(self) -> dict[str, int]:
        return {
            "distance_sum": self.distance_sum,
            "distance_samples": self.distance_samples,
            "space_sum": self.space_sum,
            "space_samples": self.space_samples,
        }


def sample(state: GameState, totals: dict[str, Behaviour]) -> None:
    """Add one sample per alive snake to ``totals``."""
    views = snake_views(state)
    config = state.config
    board = board_of(Observation(state.tick, config.width, config.height, views[0].id, views))
    for s in views:
        if not s.alive or s.heading is None:
            continue
        b = totals[s.id]
        heads = [o.body[0] for o in views if o.alive and o.id != s.id]
        if heads:
            b.distance_sum += min(manhattan(s.body[0], h) for h in heads)
            b.distance_samples += 1
        starts = [next_cell(s.body[0], d) for d in legal_moves(s.heading)]
        b.space_sum += flood_fill(board, starts, SPACE_CAP, SPACE_RADIUS)
        b.space_samples += 1
