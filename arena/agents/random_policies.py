"""Phase 1 baseline brains: a uniform random mover and a random mover that avoids instant death."""

from __future__ import annotations

import random

from arena.agents.base import Observation, hazards, legal_moves
from arena.engine import DELTAS, Direction


class RandomUniform:
    """Picks any non-reversing move uniformly. A control with no safety at all."""

    name = "random_uniform"
    version = "1"

    def __init__(self) -> None:
        self._rng = random.Random(0)

    def reset(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def choose_action(self, obs: Observation) -> Direction:
        me = obs.me
        assert me.heading is not None
        return self._rng.choice(legal_moves(me.heading))


class RandomSafe:
    """Picks uniformly among moves that do not die this tick; straight if none are safe."""

    name = "random_safe"
    version = "1"

    def __init__(self) -> None:
        self._rng = random.Random(0)

    def reset(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def choose_action(self, obs: Observation) -> Direction:
        me = obs.me
        assert me.heading is not None
        blocked = hazards(obs)
        hx, hy = me.body[0]
        w, h = obs.width, obs.height
        safe = []
        for d in legal_moves(me.heading):
            dx, dy = DELTAS[d]
            x, y = hx + dx, hy + dy
            if 0 <= x < w and 0 <= y < h and (x, y) not in blocked:
                safe.append(d)
        if not safe:
            return me.heading
        return self._rng.choice(safe)
