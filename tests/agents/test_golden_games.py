"""Pinned digests of whole personality games.

Feature and policy speed-ups must not change a single decision: these digests cover every
move, kill and death of a few short games, so any behavioural change shows up here. Update
them only for a deliberate behaviour change, and say so in the commit.
"""

import hashlib
import json

import pytest

from arena.agents.registry import PERSONALITIES, make_policy
from arena.engine import GameConfig
from arena.sim.match import Match

CASES = {
    "personalities-20": (PERSONALITIES, 20, 400, 3),
    "personalities-100": (PERSONALITIES, 100, 200, 11),
    "mixed-30": (("hunter", "random_safe", "trapper", "predictor", "random_safe"), 30, 600, 5),
    "mixed-16": (("survivor", "opportunist", "random_safe", "random_safe", "hunter"), 16, 600, 8),
}

DIGESTS = {
    "personalities-20": "7c606df2e5b865aa7e0b4c5ad94c11e2719e1f3c36bdffd67a35c2c01bb2cc21",
    "personalities-100": "5de8274c7d9165422983250684e699fd1b7f6609f0d297485a730fc11a119f9a",
    "mixed-30": "960b9863f57ff9aa37955bd496ee1c19e9deea9386575eaf8ff723463dadc150",
    "mixed-16": "7fb19c3d8407b826bf58dadb86de07910d6d00fdd99cb106944d58936d11ce81",
}


def digest(case: str) -> str:
    names, size, ticks, seed = CASES[case]
    config = GameConfig(
        width=size, height=size, snake_length=5, max_ticks=ticks, score_target=10**9
    )
    match = Match([make_policy(n) for n in names], seed, config, record=True, metrics_every=50)
    result = match.run()
    blob = json.dumps(
        {
            "result": result.to_dict(),
            "actions": match.actions,
            "events": [repr(e) for e in match.events],
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


@pytest.mark.parametrize("case", sorted(CASES))
def test_game_digest_is_unchanged(case: str) -> None:
    assert digest(case) == DIGESTS[case]
