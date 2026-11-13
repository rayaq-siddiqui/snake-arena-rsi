"""What a policy sees and the interface it implements (phase 1 spec, section 4)."""

from __future__ import annotations

from typing import NamedTuple, Protocol

from arena.engine import DELTAS, DIRECTIONS, OPPOSITE, Cell, Direction, GameState, SnakeId


class SnakeView(NamedTuple):
    id: SnakeId
    alive: bool
    body: tuple[Cell, ...]
    heading: Direction | None
    kills: int
    deaths: int
    respawn_in: int


class Observation(NamedTuple):
    """A policy's read-only view of one tick.

    Named tuples rather than frozen dataclasses: equally immutable, and several times
    cheaper to build, which matters because a match builds five of these every tick.
    """

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


_LEGAL: dict[Direction, tuple[Direction, ...]] = {
    h: tuple(d for d in DIRECTIONS if d != OPPOSITE[h]) for h in DIRECTIONS
}


def legal_moves(heading: Direction) -> tuple[Direction, ...]:
    """The three moves that are not a reversal, in fixed order."""
    return _LEGAL[heading]


_hazard_cache: list[tuple[tuple[SnakeView, ...], frozenset[Cell]]] = []


def hazards(obs: Observation) -> frozenset[Cell]:
    """Cells that will still be occupied after every snake vacates its tail.

    Every policy in a tick shares one ``snakes`` tuple, so the set is computed once per tick.
    """
    if _hazard_cache and _hazard_cache[0][0] is obs.snakes:
        return _hazard_cache[0][1]
    cells = frozenset(cell for s in obs.snakes if s.alive for cell in s.body[:-1])
    _hazard_cache[:] = [(obs.snakes, cells)]
    return cells


def next_cell(head: Cell, direction: Direction) -> Cell:
    dx, dy = DELTAS[direction]
    return head[0] + dx, head[1] + dy
