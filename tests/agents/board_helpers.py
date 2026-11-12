from __future__ import annotations

from arena.agents.base import Observation, SnakeView
from arena.engine import DELTAS, Cell, Direction


def heading_of(body: list[Cell]) -> Direction:
    dx, dy = body[0][0] - body[1][0], body[0][1] - body[1][1]
    for d, delta in DELTAS.items():
        if delta == (dx, dy):
            return d
    raise ValueError("body is not contiguous at the head")


def line(head: Cell, toward_tail: Direction, length: int = 5) -> list[Cell]:
    dx, dy = DELTAS[toward_tail]
    return [(head[0] + i * dx, head[1] + i * dy) for i in range(length)]


def observe(
    bodies: dict[str, list[Cell]], me: str = "s0", size: int = 20, num_snakes: int = 5
) -> Observation:
    """A hand-drawn observation; snakes missing from ``bodies`` are dead."""
    views = []
    for i in range(num_snakes):
        sid = f"s{i}"
        if sid in bodies:
            body = tuple(bodies[sid])
            views.append(SnakeView(sid, True, body, heading_of(list(body)), 0, 0, 0))
        else:
            views.append(SnakeView(sid, False, (), None, 0, 0, 5))
    return Observation(0, size, size, me, tuple(views))
