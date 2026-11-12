"""Predictor: simulates every nearby enemy's next moves and scores by expected value.

Each enemy is assumed to pick uniformly among its safe moves (straight on if it has
none). That gives a probability map of each enemy's head ``lookahead`` ticks ahead. A
move's expected value is kills it makes likely, plus pressure on enemies' escape moves,
minus the chance of dying on the best path through the next ``lookahead`` ticks.
"""

from __future__ import annotations

from collections.abc import Mapping

from arena.agents.base import legal_moves, next_cell
from arena.agents.features import Board, enemy_options, manhattan
from arena.agents.params import Param, ParamSet, ParamSpace
from arena.agents.scorer import ScoringPolicy, common_params, weight
from arena.engine import Cell, Direction, SnakeId

Layer = dict[tuple[Cell, Direction], float]


def enemy_layers(board: Board, enemy_id: SnakeId, depth: int) -> list[Layer]:
    """Probability of the enemy's (head, heading) after 1..depth ticks."""
    enemy = board.snakes[enemy_id]
    assert enemy.heading is not None
    first: Layer = {}
    options = enemy_options(board, enemy)
    for d in options:
        key = (next_cell(enemy.body[0], d), d)
        first[key] = first.get(key, 0.0) + 1 / len(options)
    layers = [first]
    for _ in range(depth - 1):
        layer: Layer = {}
        for (head, heading), p in layers[-1].items():
            if not board.free(head):
                continue
            safe = [d for d in legal_moves(heading) if board.free(next_cell(head, d))]
            for d in safe or [heading]:
                key = (next_cell(head, d), d)
                layer[key] = layer.get(key, 0.0) + p / len(safe or [heading])
        layers.append(layer)
    return layers


class Predictor(ScoringPolicy):
    name = "predictor"
    param_space = ParamSpace(
        (
            *common_params(keep_distance=3, keep_repel=1.0, pull_radius=15),
            weight("territory", 20.0),
            weight("space", 6.0),
            weight("space_vs_length", 20.0),
            weight("nearest_enemy_head", -20.0),
            weight("straightness", 0.01, -10.0, 10.0),
            Param("w_expected_kills", 300.0, 0.0, 2000.0),
            Param("w_pressure", 10.0, -200.0, 200.0),
            Param("w_expected_death", -300.0, -2000.0, 0.0),
            Param("lookahead", 2, 1, 3, "int"),
            Param("discount", 0.5, 0.0, 1.0),
        )
    )

    def __init__(self, params: ParamSet | None = None) -> None:
        super().__init__(params)
        self._tick_board: Board | None = None
        self._danger: list[dict[Cell, float]] = []
        self._layers: dict[SnakeId, list[Layer]] = {}

    def _prepare(self, board: Board, me: SnakeId) -> None:
        if self._tick_board is board:
            return
        self._tick_board = board
        depth = int(self.params["lookahead"])
        head = board.snakes[me].body[0]
        reach = int(self.params["search_radius"]) + depth
        self._layers = {
            e.id: enemy_layers(board, e.id, depth)
            for e in board.enemies(me)
            if manhattan(e.body[0], head) <= reach
        }
        # danger[t][cell]: chance some enemy head is on ``cell`` at tick t+1 or was at tick t.
        self._danger = []
        for t in range(depth):
            safe_prob: dict[Cell, float] = {}
            for layers in self._layers.values():
                here: dict[Cell, float] = {}
                for k in (t, t - 1):
                    if k < 0:
                        continue
                    for (cell, _), p in layers[k].items():
                        here[cell] = min(1.0, here.get(cell, 0.0) + p)
                for cell, p in here.items():
                    safe_prob[cell] = safe_prob.get(cell, 1.0) * (1 - p)
            self._danger.append({c: 1 - s for c, s in safe_prob.items()})

    def _death(
        self, board: Board, cell: Cell, heading: Direction, t: int, path: set[Cell]
    ) -> float:
        if not board.free(cell) or cell in path:
            return 1.0
        risk = self._danger[t].get(cell, 0.0)
        if t + 1 >= len(self._danger):
            return risk
        path = path | {cell}
        best = min(
            self._death(board, next_cell(cell, d), d, t + 1, path) for d in legal_moves(heading)
        )
        return risk + (1 - risk) * self.params["discount"] * best

    def _kills_and_pressure(self, board: Board, me: SnakeId, target: Cell) -> tuple[float, float]:
        mine = set(board.snakes[me].body[:-1]) | {target}
        kills = pressure = 0.0
        for layers in self._layers.values():
            for (head, heading), p in layers[0].items():
                if not board.free(head) or head == target:
                    continue
                escapes = [
                    d
                    for d in legal_moves(heading)
                    if (c := next_cell(head, d)) != target and board.free(c)
                ]
                pressure += p * (1 - len(escapes) / 3)
                if not escapes and next_cell(head, heading) in mine:
                    kills += p
        return kills, pressure

    def extra_score(self, board: Board, me: SnakeId, move: Direction) -> float:
        self._prepare(board, me)
        p: Mapping[str, float] = self.params
        target = next_cell(board.snakes[me].body[0], move)
        death = self._death(board, target, move, 0, set())
        kills, pressure = self._kills_and_pressure(board, me, target)
        return (
            p["w_expected_kills"] * kills
            + p["w_pressure"] * pressure
            + p["w_expected_death"] * death
        )
