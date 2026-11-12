"""Hunter: closes in on enemy heads and lays its body across their path (phase 2 spec)."""

from __future__ import annotations

from arena.agents.params import ParamSpace
from arena.agents.scorer import ScoringPolicy, common_params, weight


class Hunter(ScoringPolicy):
    name = "hunter"
    param_space = ParamSpace(
        (
            *common_params(keep_distance=1),
            weight("head_on_risk", -40.0),
            weight("territory", 20.0),
            weight("space", 6.0),
            weight("space_vs_length", 20.0),
            weight("nearest_enemy_head", -30.0),
            weight("straightness", 0.01, -10.0, 10.0),
            weight("cut_off", 12.0),
        )
    )
