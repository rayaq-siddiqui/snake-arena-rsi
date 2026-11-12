"""Move features shared by every personality (phase 2 spec, section 1).

Each feature is a deterministic function of the board, the snake choosing and one of its
moves. ``Board`` is built once per tick from an observation and shared by every snake, so
the per-move work is only the feature itself.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from arena.agents.base import Observation, SnakeView, hazards, legal_moves, next_cell
from arena.engine import DELTAS, Cell, Direction, SnakeId

DEFAULT_SPACE_CAP = 60
DEFAULT_SEARCH_RADIUS = 12
DEFAULT_TRAP_MARGIN = 2.0
DEFAULT_CUT_OFF_LENGTH = 5
DEFAULT_KEEP_DISTANCE = 0
DEFAULT_KEEP_REPEL = 0.0


@dataclass(frozen=True)
class Board:
    """The start-of-tick board as every policy sees it, with per-snake move options.

    ``grid`` is the blocked map on a board padded with a one-cell wall, indexed by
    ``index(x, y)``, so searches test a cell with one byte lookup instead of a bounds
    check and a set lookup.
    """

    width: int
    height: int
    blocked: frozenset[Cell]
    snakes: Mapping[SnakeId, SnakeView]
    safe_moves: Mapping[SnakeId, tuple[Direction, ...]]
    grid: bytes = b""
    memo: dict[tuple[object, ...], int] = field(default_factory=dict, compare=False, repr=False)

    def on_board(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.width and 0 <= cell[1] < self.height

    def free(self, cell: Cell) -> bool:
        return self.on_board(cell) and cell not in self.blocked

    def index(self, cell: Cell) -> int:
        return (cell[1] + 1) * stride_of(self.width) + cell[0] + 1

    def enemies(self, me: SnakeId) -> list[SnakeView]:
        return [s for s in self.snakes.values() if s.alive and s.id != me]

    def nearby_enemies(self, me: SnakeId, cell: Cell, radius: int) -> list[SnakeView]:
        return [s for s in self.enemies(me) if manhattan(s.body[0], cell) <= radius]


_board_cache: list[tuple[tuple[SnakeView, ...], Board]] = []
_geometry_cache: dict[tuple[int, int], bytes] = {}
_diamond_cache: dict[tuple[int, int, int], tuple[bytes, int]] = {}


def stride_of(width: int) -> int:
    """Row length of the padded grid: wide enough that an index difference names exactly
    one (dx, dy), so a Manhattan-radius test is one lookup in ``diamond``."""
    return 2 * width + 3


def geometry(width: int, height: int) -> bytes:
    """The empty padded grid: 1 (wall) everywhere except the board's own cells."""
    key = (width, height)
    if key not in _geometry_cache:
        stride = stride_of(width)
        empty = bytearray(b"\x01" * (stride * (height + 2)))
        for y in range(height):
            start = (y + 1) * stride + 1
            empty[start : start + width] = bytes(width)
        _geometry_cache[key] = bytes(empty)
    return _geometry_cache[key]


def diamond(width: int, height: int, radius: int) -> tuple[bytes, int]:
    """``(inside, base)``: ``inside[j - i + base]`` is 1 when padded cells ``i`` and ``j``
    are within Manhattan ``radius`` of each other."""
    key = (width, height, radius)
    if key not in _diamond_cache:
        stride = stride_of(width)
        dy_max, dx_max = height + 1, width + 1
        base = dy_max * stride + dx_max
        inside = bytearray((2 * dy_max + 1) * stride)
        for dy in range(-dy_max, dy_max + 1):
            for dx in range(-dx_max, dx_max + 1):
                if abs(dx) + abs(dy) <= radius:
                    inside[dy * stride + dx + base] = 1
        _diamond_cache[key] = (bytes(inside), base)
    return _diamond_cache[key]


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
    grid = bytearray(geometry(w, h))
    stride = stride_of(w)
    for x, y in blocked:
        if 0 <= x < w and 0 <= y < h:
            grid[(y + 1) * stride + x + 1] = 1
    board = Board(w, h, blocked, {s.id: s for s in obs.snakes}, safe, bytes(grid))
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
    bounded on any board size. The count does not depend on search order, so results
    without ``extra_blocked`` are memoised for the tick.
    """
    w, h = board.width, board.height
    blocked = board.blocked
    extra = set(extra_blocked)
    starts = list(dict.fromkeys(c for c in starts if _free(c, w, h, blocked) and c not in extra))
    if not starts:
        return 0
    key: tuple[object, ...] | None = None
    if not extra:
        key = ("fill", *starts, cap, radius)
        if key in board.memo:
            return board.memo[key]
    count = _fill(board, starts, cap, radius, extra)
    if key is not None:
        board.memo[key] = count
    return count


def _fill(board: Board, starts: list[Cell], cap: int, radius: int, extra: set[Cell]) -> int:
    stride = stride_of(board.width)
    inside, base = diamond(board.width, board.height, radius)
    seen = bytearray(board.grid)
    for c in extra:
        if board.on_board(c):
            seen[board.index(c)] = 1
    queue = [board.index(c) for c in starts]
    shift = base - queue[0]
    for i in queue:
        seen[i] = 1
    count = len(queue)
    head = 0
    while head < len(queue) and count < cap:
        i = queue[head]
        head += 1
        for j in (i - stride, i + 1, i + stride, i - 1):
            if seen[j] or not inside[j + shift]:
                continue
            seen[j] = 1
            queue.append(j)
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


def territory(board: Board, me: SnakeId, move: Direction, p: Params) -> float:
    """Cells my new head reaches strictly before every enemy head (capped), over the cap.

    A breadth-first race: enemies start from their heads now, I start from the new head one
    tick later, and a cell belongs to whoever arrives first; ties belong to nobody. Unlike
    ``space`` this sees a corridor an enemy will close before I get through it.
    """
    cap, radius = _cap(p), _radius(p)
    target = _target(board, me, move)
    if not board.free(target):
        return 0.0
    key = ("territory", me, target, cap, radius)
    if key not in board.memo:
        board.memo[key] = _territory(board, me, target, cap, radius)
    return min(board.memo[key], cap) / cap


def _territory(board: Board, me: SnakeId, target: Cell, cap: int, radius: int) -> int:
    """The race in ``territory`` on the padded grid.

    ``taken`` holds 0 for free, 1 for taken, ``mine_mark`` for cells I reach in the layer
    being built, and ``tie_mark`` for cells both sides reach in it: those belong to nobody
    but still extend the enemy front.
    """
    stride = stride_of(board.width)
    far = 2 * radius
    taken = bytearray(board.grid)
    start = board.index(target)
    near_in, near_base = diamond(board.width, board.height, radius)
    far_in, far_base = diamond(board.width, board.height, far)
    near_shift, far_shift = near_base - start, far_base - start
    steps = (-stride, 1, stride, -1)
    mine_mark, tie_mark = 2, 3

    heads = {
        board.index(e.body[0]) for e in board.enemies(me) if manhattan(e.body[0], target) <= far
    }
    taken[start] = 1
    for i in heads:
        taken[i] = 1
    enemy: list[int] = []
    for i in heads:
        for d in steps:
            c = i + d
            if not taken[c] and far_in[c + far_shift]:
                taken[c] = 1
                enemy.append(c)
    mine = [start]
    count = 1
    while mine and count < cap:
        mine_next: list[int] = []
        for i in mine:
            for d in steps:
                c = i + d
                if not taken[c] and near_in[c + near_shift]:
                    taken[c] = mine_mark
                    mine_next.append(c)
        grown: list[int] = []
        for i in enemy:
            for d in steps:
                c = i + d
                t = taken[c]
                if (t == 0 or t == mine_mark) and far_in[c + far_shift]:
                    taken[c] = tie_mark if t else 1
                    grown.append(c)
        mine = [c for c in mine_next if taken[c] == mine_mark]
        for c in mine_next:
            taken[c] = 1
        for c in grown:
            taken[c] = 1
        enemy = grown
        count += len(mine)
    return count


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
    """Distance from the new head to the nearest enemy head over (width + height); 1 if none.

    A distance d below ``keep_distance`` k counts as ``k + keep_repel * (k - d)``. A snake
    pulled toward heads (negative weight) therefore stops at distance k instead of pressing
    in to where every move risks a head-on crash; with ``keep_repel`` > 0 it also backs off
    when an enemy comes closer than k. With ``pull_radius`` r > 0, enemies farther than r
    count as absent (1.0), so the pull only acts on snakes already nearby.
    """
    target = _target(board, me, move)
    heads = [e.body[0] for e in board.enemies(me)]
    if not heads:
        return 1.0
    keep = int(p.get("keep_distance", DEFAULT_KEEP_DISTANCE))
    d: float = min(manhattan(target, h) for h in heads)
    reach = int(p.get("pull_radius", 0))
    if reach and d > reach:
        return 1.0
    if d < keep:
        d = keep + p.get("keep_repel", DEFAULT_KEEP_REPEL) * (keep - d)
    return d / (board.width + board.height)


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
        territory,
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
