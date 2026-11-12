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
    "personalities-20": "50ca9a5caebba34f3214ddb002f3523a24badb93128101b79c9cd77e8d95e5c2",
    "personalities-100": "30c055e2d80283aff0e004b7b611004a78af94938593b6439cb43399f7bcfa0c",
    "mixed-30": "093eb919bbd3d0b80f7d7af54bf90b84a7aac790d197ebde1dd76bb73d9493d0",
    "mixed-16": "e8086023e6a64b863fcca883fb9ed0408f58f814fdfae4763b107b891e117581",
}


def digest(case: str) -> str:
    names, size, ticks, seed = CASES[case]
    config = GameConfig(width=size, height=size, max_ticks=ticks, score_target=10**9)
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
