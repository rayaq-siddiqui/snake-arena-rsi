"""Seeded, safe placement of snakes (phase 1 spec, section 3)."""

from __future__ import annotations

from collections.abc import Iterable

from arena.engine.rng import randbelow
from arena.engine.types import DELTAS, DIRECTIONS, Cell, Direction, GameConfig


def spawn_cells(head: Cell, heading: Direction, length: int) -> tuple[Cell, ...]:
    dx, dy = DELTAS[heading]
    return tuple((head[0] - i * dx, head[1] - i * dy) for i in range(length))


def is_valid_spawn(
    head: Cell, heading: Direction, config: GameConfig, occupied: frozenset[Cell] | set[Cell]
) -> bool:
    w, h = config.width, config.height
    cells = spawn_cells(head, heading, config.snake_length)
    for x, y in cells:
        if not (0 <= x < w and 0 <= y < h):
            return False
    dx, dy = DELTAS[heading]
    hx, hy = head
    for i in range(1, config.spawn_lookahead + 1):
        ax, ay = hx + i * dx, hy + i * dy
        if not (0 <= ax < w and 0 <= ay < h) or (ax, ay) in occupied:
            return False
    if not occupied:
        return True
    r = config.spawn_clearance
    for x, y in cells:
        for nx in range(x - r, x + r + 1):
            for ny in range(y - r, y + r + 1):
                if (nx, ny) in occupied:
                    return False
    return True


def find_spawn(
    rng_state: int, config: GameConfig, occupied: frozenset[Cell] | set[Cell]
) -> tuple[int, tuple[Cell, ...] | None, Direction | None]:
    """Return ``(new_rng_state, cells, heading)``; cells is None when nothing fits.

    Tries ``spawn_attempts`` seeded random placements, then a deterministic row-major
    scan, so the result depends only on the RNG state and the occupied cells.
    """
    for _ in range(config.spawn_attempts):
        rng_state, x = randbelow(rng_state, config.width)
        rng_state, y = randbelow(rng_state, config.height)
        rng_state, d = randbelow(rng_state, len(DIRECTIONS))
        heading = DIRECTIONS[d]
        if is_valid_spawn((x, y), heading, config, occupied):
            return rng_state, spawn_cells((x, y), heading, config.snake_length), heading
    for y in range(config.height):
        for x in range(config.width):
            for heading in DIRECTIONS:
                if is_valid_spawn((x, y), heading, config, occupied):
                    return rng_state, spawn_cells((x, y), heading, config.snake_length), heading
    return rng_state, None, None


def occupied_by(bodies: Iterable[tuple[Cell, ...]]) -> set[Cell]:
    return {cell for body in bodies for cell in body}
