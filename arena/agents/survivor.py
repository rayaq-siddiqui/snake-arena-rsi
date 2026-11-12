"""Survivor: keeps to open space, away from walls and head-on fights (phase 2 spec)."""

from __future__ import annotations

from arena.agents.params import ParamSpace
from arena.agents.scorer import ScoringPolicy, common_params, weight


class Survivor(ScoringPolicy):
    name = "survivor"
    param_space = ParamSpace(
        (
            *common_params(keep_distance=3, keep_repel=1.0, pull_radius=15),
            weight("head_on_risk", -100.0),
            weight("territory", 40.0),
            weight("space", 20.0),
            weight("space_vs_length", 40.0),
            weight("wall_distance", 1.0),
            weight("nearest_enemy_head", -8.0),
            weight("enemy_escape_moves", -3.0),
        )
    )
