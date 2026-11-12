"""Trapper: shrinks nearby enemies' space and escape moves until they have none (phase 2 spec)."""

from __future__ import annotations

from arena.agents.params import ParamSpace
from arena.agents.scorer import ScoringPolicy, common_params, weight


class Trapper(ScoringPolicy):
    name = "trapper"
    param_space = ParamSpace(
        (
            *common_params(keep_distance=3, keep_repel=1.0, pull_radius=15),
            weight("head_on_risk", -40.0),
            weight("territory", 20.0),
            weight("space", 6.0),
            weight("space_vs_length", 20.0),
            weight("enemy_space_after", -15.0),
            weight("enemy_escape_moves", -10.0),
            weight("nearest_enemy_head", -20.0),
            weight("straightness", 0.01, -10.0, 10.0),
            weight("cut_off", 4.0),
        )
    )
