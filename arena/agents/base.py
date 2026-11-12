"""What a policy sees and the interface it implements (phase 1 spec, section 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from arena.engine import DELTAS, DIRECTIONS, OPPOSITE, Cell, Direction, GameState, SnakeId


@dataclass(frozen=True)
class SnakeView:
    id: SnakeId
    alive: bool
    body: tuple[Cell, ...]
    heading: Direction | None
    kills: int
    deaths: int
    respawn_in: int


@dataclass(frozen=True)
class Observation:
    tick: int
    width: int
    height: int
    self_id: SnakeId
    snakes: tuple[SnakeView, ...]

    @property
    def me(self) -> SnakeView:
        for s in self.snakes:
            if s.id == self.self_id:
                return s
        raise KeyError(self.self_id)


class Policy(Protocol):
    name: str
    version: str

    def reset(self, seed: int) -> None: ...

    def choose_action(self, obs: Observation) -> Direction: ...


def snake_views(state: GameState) -> tuple[SnakeView, ...]:
    return tuple(
        SnakeView(s.id, s.alive, s.body, s.heading, s.kills, s.deaths, s.respawn_in)
        for s in state.snakes
    )


def legal_moves(heading: Direction) -> tuple[Direction, ...]:
    """The three moves that are not a reversal, in fixed order."""
    return tuple(d for d in DIRECTIONS if d != OPPOSITE[heading])


def hazards(obs: Observation) -> set[Cell]:
    """Cells that will still be occupied after every snake vacates its tail."""
    return {cell for s in obs.snakes if s.alive for cell in s.body[:-1]}


def next_cell(head: Cell, direction: Direction) -> Cell:
    dx, dy = DELTAS[direction]
    return head[0] + dx, head[1] + dy
