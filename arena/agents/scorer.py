"""The weighted-sum move scorer every personality is built on (phase 2 spec, section 1).

``score(move) = sum(weight[f] * feature_f(move))`` over the personality's non-zero
weights; the best move wins, ties go to the fixed order UP, RIGHT, DOWN, LEFT unless the
personality opts into seeded random tie-breaks.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import ClassVar

from arena.agents.base import Observation, legal_moves
from arena.agents.features import FEATURES, Board, board_of
from arena.agents.params import Param, ParamSet, ParamSpace, load_params
from arena.engine import Direction, SnakeId

TIE_EPSILON = 1e-9


def weight(feature: str, default: float, low: float = -200.0, high: float = 200.0) -> Param:
    if feature not in FEATURES:
        raise ValueError(f"unknown feature {feature!r}")
    return Param(f"w_{feature}", default, low, high)


COMMON_PARAMS: tuple[Param, ...] = (
    weight("immediate_death", -1000.0, -5000.0, 0.0),
    Param("space_cap", 60, 10, 200, "int"),
    Param("search_radius", 12, 4, 30, "int"),
    Param("trap_margin", 2.0, 1.0, 5.0),
    Param("keep_distance", 0, 0, 10, "int"),
    Param("keep_repel", 0.0, 0.0, 5.0),
    Param("pull_radius", 0, 0, 200, "int"),
    Param("random_tiebreak", 1, 0, 1, "int"),
)


def common_params(**defaults: float) -> tuple[Param, ...]:
    """``COMMON_PARAMS`` with some defaults changed for one personality (bounds stay)."""
    unknown = set(defaults) - {p.name for p in COMMON_PARAMS}
    if unknown:
        raise ValueError(f"unknown common parameters: {', '.join(sorted(unknown))}")
    return tuple(
        Param(p.name, defaults.get(p.name, p.default), p.low, p.high, p.kind) for p in COMMON_PARAMS
    )


def feature_weights(params: Mapping[str, float], prefix: str = "w_") -> dict[str, float]:
    """The non-zero ``<prefix><feature>`` weights in ``params``, keyed by feature name."""
    out = {}
    for key, value in params.items():
        if key.startswith(prefix) and key[len(prefix) :] in FEATURES and value:
            out[key[len(prefix) :]] = float(value)
    return out


class ScoringPolicy:
    """Base class: subclasses set ``name`` and ``param_space`` and may override hooks."""

    name: str
    param_space: ClassVar[ParamSpace]

    def __init__(self, params: ParamSet | None = None) -> None:
        self.param_set = params or load_params(self.name, self.param_space)
        self.params: dict[str, float] = dict(self.param_space.validate(self.param_set.params))
        self.version = str(self.param_set.version)
        self._weights = feature_weights(self.params)
        self._rng = random.Random(0)

    def reset(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def weights(self, board: Board, me: SnakeId) -> Mapping[str, float]:
        """The weights for this tick. Personalities with modes override this."""
        return self._weights

    def extra_score(self, board: Board, me: SnakeId, move: Direction) -> float:
        """Score added on top of the weighted features (the Predictor's expected value)."""
        return 0.0

    def score_moves(self, board: Board, me: SnakeId) -> dict[Direction, float]:
        heading = board.snakes[me].heading
        assert heading is not None
        weights = self.weights(board, me)
        p = self.params
        return {
            move: sum(w * FEATURES[f](board, me, move, p) for f, w in weights.items())
            + self.extra_score(board, me, move)
            for move in legal_moves(heading)
        }

    def choose_action(self, obs: Observation) -> Direction:
        scores = self.score_moves(board_of(obs), obs.self_id)
        best = max(scores.values())
        tied = [m for m, s in scores.items() if s >= best - TIE_EPSILON]
        if len(tied) > 1 and self.params["random_tiebreak"]:
            return self._rng.choice(tied)
        return tied[0]
