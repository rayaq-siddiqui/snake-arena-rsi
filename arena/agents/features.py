"""Move features shared by every personality (phase 2 spec, section 1).

Each feature is a deterministic function of the board, the snake choosing and one of its
moves. ``Board`` is built once per tick from an observation and shared by every snake, so
the per-move work is only the feature itself.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from arena.agents.base import Observation, SnakeView, hazards, legal_moves, next_cell
from arena.engine import DELTAS, Cell, Direction, SnakeId

DEFAULT_SPACE_CAP = 60
DEFAULT_SEARCH_RADIUS = 12
DEFAULT_TRAP_MARGIN = 2.0
DEFAULT_CUT_OFF_LENGTH = 5


@dataclass(frozen=True)
class Board:
    """The start-of-tick board as every policy sees it, with per-snake move options."""

    width: int
    height: int
    blocked: frozenset[Cell]
    snakes: Mapping[SnakeId, SnakeView]
    safe_moves: Mapping[SnakeId, tuple[Direction, ...]]

    def on_board(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.width and 0 <= cell[1] < self.height

    def free(self, cell: Cell) -> bool:
        return self.on_board(cell) and cell not in self.blocked

    def enemies(self, me: SnakeId) -> list[SnakeView]:
        return [s for s in self.snakes.values() if s.alive and s.id != me]

    def nearby_enemies(self, me: SnakeId, cell: Cell, radius: int) -> list[SnakeView]:
        return [s for s in self.enemies(me) if manhattan(s.body[0], cell) <= radius]


_board_cache: list[tuple[tuple[SnakeView, ...], Board]] = []


def board_of(obs: Observation) -> Board:
    """The shared ``Board`` for this tick; built once and reused by every snake."""
    if _board_cache and _board_cache[0][0] is obs.snakes:
        return _board_cache[0][1]
    blocked = hazards(obs)
    w, h = obs.width, obs.height
    safe: dict[SnakeId, tuple[Direction, ...]] = {}
    for s in obs.snakes:
        if s.alive and s.heading is not None:
            safe[s.id] = tuple(
                d for d in legal_moves(s.heading) if _free(next_cell(s.body[0], d), w, h, blocked)
            )
    board = Board(w, h, blocked, {s.id: s for s in obs.snakes}, safe)
    _board_cache[:] = [(obs.snakes, board)]
    return board


def _free(cell: Cell, w: int, h: int, blocked: frozenset[Cell] | set[Cell]) -> bool:
    return 0 <= cell[0] < w and 0 <= cell[1] < h and cell not in blocked


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def flood_fill(
    board: Board,
    starts: Iterable[Cell],
    cap: int,
    radius: int,
    extra_blocked: Iterable[Cell] = (),
) -> int:
    """Free cells reachable from ``starts`` (which count if free), at most ``cap``.

    The search stays within Manhattan ``radius`` of the first start, so a tick's cost is
    bounded on any board size.
    """
    w, h = board.width, board.height
    blocked = board.blocked
    extra = set(extra_blocked)
    starts = [c for c in starts if _free(c, w, h, blocked) and c not in extra]
    if not starts:
        return 0
    ox, oy = starts[0]
    seen = set(starts)
    queue = deque(starts)
    count = len(seen)
    while queue and count < cap:
        x, y = queue.popleft()
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            c = (x + dx, y + dy)
            if c in seen:
                continue
            if abs(c[0] - ox) + abs(c[1] - oy) > radius:
                continue
            if not (0 <= c[0] < w and 0 <= c[1] < h) or c in blocked or c in extra:
                continue
            seen.add(c)
            queue.append(c)
            count += 1
            if count >= cap:
                break
    return min(count, cap)


def enemy_options(board: Board, enemy: SnakeView) -> tuple[Direction, ...]:
    """The moves an enemy is assumed to pick from: its safe moves, or all legal ones."""
    assert enemy.heading is not None
    return board.safe_moves.get(enemy.id) or legal_moves(enemy.heading)


Params = Mapping[str, float]


def _cap(p: Params) -> int:
    return int(p.get("space_cap", DEFAULT_SPACE_CAP))


def _radius(p: Params) -> int:
    return int(p.get("search_radius", DEFAULT_SEARCH_RADIUS))


def _target(board: Board, me: SnakeId, move: Direction) -> Cell:
    return next_cell(board.snakes[me].body[0], move)


def immediate_death(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    """1 if the move certainly dies this tick: off the board or into a body cell."""
    return 0.0 if board.free(_target(board, me, move)) else 1.0


def head_on_risk(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    """Chance some enemy head also enters the target cell, each enemy picking uniformly."""
    target = _target(board, me, move)
    survive = 1.0
    for e in board.enemies(me):
        if manhattan(e.body[0], target) != 1:
            continue
        options = enemy_options(board, e)
        hits = sum(next_cell(e.body[0], d) == target for d in options)
        survive *= 1 - hits / len(options)
    return 1 - survive


def space(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    """Reachable cells from the new head (capped), as a share of the cap."""
    cap = _cap(p)
    return flood_fill(board, [_target(board, me, move)], cap, _radius(p)) / cap


def space_vs_length(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    """1 if reachable space is at least ``trap_margin`` times my length."""
    need = len(board.snakes[me].body) * p.get("trap_margin", DEFAULT_TRAP_MARGIN)
    cap = max(_cap(p), int(need) + 1)
    reach = flood_fill(board, [_target(board, me, move)], cap, _radius(p))
    return 1.0 if reach >= need else 0.0


def wall_distance(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    """Distance from the new head to the nearest wall; 0 at a wall, 1 at the centre."""
    x, y = _target(board, me, move)
    d = min(x, y, board.width - 1 - x, board.height - 1 - y)
    half = max(1, (min(board.width, board.height) - 1) // 2)
    return max(0.0, min(1.0, d / half))


def nearest_enemy_head(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    """Distance from the new head to the nearest enemy head over (width + height); 1 if none."""
    target = _target(board, me, move)
    heads = [e.body[0] for e in board.enemies(me)]
    if not heads:
        return 1.0
    return min(manhattan(target, h) for h in heads) / (board.width + board.height)


def enemy_space_after(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    """Mean reachable space of nearby enemies if my head moves here; 1 if nobody is near."""
    target = _target(board, me, move)
    cap, radius = _cap(p), _radius(p)
    near = board.nearby_enemies(me, target, radius)
    if not near:
        return 1.0
    total = 0
    for e in near:
        starts = [next_cell(e.body[0], d) for d in enemy_options(board, e)]
        total += flood_fill(board, starts, cap, radius, extra_blocked=(target,))
    return total / (cap * len(near))


def enemy_escape_moves(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    """Safe moves the nearest enemy keeps after my move, over 3; 1 if nobody is near."""
    target = _target(board, me, move)
    near = board.nearby_enemies(me, target, _radius(p))
    if not near:
        return 1.0
    e = min(near, key=lambda s: (manhattan(s.body[0], target), s.id))
    assert e.heading is not None
    free = sum(
        1
        for d in legal_moves(e.heading)
        if (c := next_cell(e.body[0], d)) != target and board.free(c)
    )
    return free / 3


def cut_off(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    """1 if the new head lands on a nearby enemy's straight-ahead path (2+ cells ahead)."""
    target = _target(board, me, move)
    length = int(p.get("cut_off_length", DEFAULT_CUT_OFF_LENGTH))
    for e in board.nearby_enemies(me, target, _radius(p)):
        assert e.heading is not None
        dx, dy = DELTAS[e.heading]
        hx, hy = e.body[0]
        for k in range(2, length + 1):
            if (hx + k * dx, hy + k * dy) == target:
                return 1.0
    return 0.0


def centre_distance(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    """Manhattan distance from the board centre, normalised to 0..1."""
    x, y = _target(board, me, move)
    cx, cy = (board.width - 1) / 2, (board.height - 1) / 2
    return (abs(x - cx) + abs(y - cy)) / max(1.0, cx + cy)


def straightness(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    return 1.0 if move == board.snakes[me].heading else 0.0


Feature = Callable[[Board, SnakeId, Direction, Params], float]

FEATURES: dict[str, Feature] = {
    f.__name__: f
    for f in (
        immediate_death,
        head_on_risk,
        space,
        space_vs_length,
        wall_distance,
        nearest_enemy_head,
        enemy_space_after,
        enemy_escape_moves,
        cut_off,
        centre_distance,
        straightness,
    )
}
