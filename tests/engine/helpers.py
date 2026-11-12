from __future__ import annotations

from arena.engine import DELTAS, Cell, Direction, GameConfig, GameState, SnakeState

Bodies = dict[str, list[Cell]]


def heading_of(body: list[Cell]) -> Direction:
    dx, dy = body[0][0] - body[1][0], body[0][1] - body[1][1]
    for d, delta in DELTAS.items():
        if delta == (dx, dy):
            return d
    raise ValueError("body is not contiguous at the head")


def make_state(bodies: Bodies, config: GameConfig | None = None, **snake_extra: dict) -> GameState:
    """Build a hand-drawn state. Snakes not in ``bodies`` are dead with no respawn pending."""
    if config is None:
        length = len(next(iter(bodies.values()))) if bodies else 5
        config = GameConfig(width=10, height=10, num_snakes=5, snake_length=length)
    snakes = []
    for sid in config.snake_ids:
        extra = snake_extra.get(sid, {})
        if sid in bodies:
            body = tuple(bodies[sid])
            snakes.append(
                SnakeState(id=sid, body=body, heading=heading_of(list(body)), alive=True, **extra)
            )
        else:
            snakes.append(SnakeState(id=sid, respawn_in=10**9, **extra))
    return GameState(config=config, snakes=tuple(snakes), rng_state=12345)


def line(head: Cell, toward_tail: Direction, length: int) -> list[Cell]:
    dx, dy = DELTAS[toward_tail]
    return [(head[0] + i * dx, head[1] + i * dy) for i in range(length)]
