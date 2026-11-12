"""Opportunist: cruises safely, and attacks only when a nearby enemy is nearly boxed in.

It has two weight sets. Each tick it attacks if some enemy within ``search_radius`` has at
most ``attack_threshold`` safe moves, and cruises otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping

from arena.agents.features import FEATURES, Board, manhattan
from arena.agents.params import Param, ParamSet, ParamSpace
from arena.agents.scorer import ScoringPolicy, common_params, feature_weights
from arena.engine import SnakeId


def mode_weight(mode: str, feature: str, default: float) -> Param:
    assert feature in FEATURES
    return Param(f"{mode}_{feature}", default, -200.0, 200.0)


class Opportunist(ScoringPolicy):
    name = "opportunist"
    param_space = ParamSpace(
        (
            *common_params(keep_distance=4, keep_repel=1.0, pull_radius=15),
            Param("attack_threshold", 1, 0, 3, "int"),
            mode_weight("cruise", "head_on_risk", -100.0),
            mode_weight("cruise", "territory", 30.0),
            mode_weight("cruise", "space", 15.0),
            mode_weight("cruise", "space_vs_length", 30.0),
            mode_weight("cruise", "nearest_enemy_head", -20.0),
            mode_weight("cruise", "straightness", 0.01),
            mode_weight("attack", "head_on_risk", -40.0),
            mode_weight("attack", "territory", 20.0),
            mode_weight("attack", "space", 6.0),
            mode_weight("attack", "space_vs_length", 20.0),
            mode_weight("attack", "nearest_enemy_head", -10.0),
            mode_weight("attack", "enemy_escape_moves", -20.0),
            mode_weight("attack", "enemy_space_after", -10.0),
            mode_weight("attack", "cut_off", 10.0),
        )
    )

    def __init__(self, params: ParamSet | None = None) -> None:
        super().__init__(params)
        base = feature_weights(self.params)
        self.cruise = {**base, **feature_weights(self.params, "cruise_")}
        self.attack = {**base, **feature_weights(self.params, "attack_")}

    def attacking(self, board: Board, me: SnakeId) -> bool:
        head = board.snakes[me].body[0]
        radius = int(self.params["search_radius"])
        threshold = self.params["attack_threshold"]
        return any(
            len(board.safe_moves.get(e.id, ())) <= threshold
            for e in board.enemies(me)
            if manhattan(e.body[0], head) <= radius
        )

    def weights(self, board: Board, me: SnakeId) -> Mapping[str, float]:
        return self.attack if self.attacking(board, me) else self.cruise
