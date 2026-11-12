"""Named board configurations.

``default`` is the game as specified (phase 1). ``experiment`` is a smaller board for
phase 4 runs: on 100 x 100 the phase 2 personalities almost never meet, so all-five
matches score about one kill per 100,000 ticks (see specs/plan.md, Measurements).
Results on ``experiment`` must be labelled as such; the default rules never change.
"""

from __future__ import annotations

from arena.engine import GameConfig

BOARDS: dict[str, GameConfig] = {
    "default": GameConfig(),
    "experiment": GameConfig(width=50, height=50),
}


def board(name: str) -> GameConfig:
    if name not in BOARDS:
        raise ValueError(f"unknown board {name!r}; choose from {', '.join(BOARDS)}")
    return BOARDS[name]
