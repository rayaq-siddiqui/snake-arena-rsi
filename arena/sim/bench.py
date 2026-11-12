"""Speed and kill-rate measurements (phase 1 spec, section 10)."""

from __future__ import annotations

import platform
import random
import time
from collections.abc import Sequence

from arena.agents import make_policy
from arena.agents.base import legal_moves
from arena.engine import GameConfig, new_game, step
from arena.sim.match import Match


def engine_ticks_per_second(config: GameConfig, ticks: int, seed: int) -> float:
    """Engine alone: actions come from a bare RNG, no observations are built."""
    config = GameConfig.from_dict({**config.to_dict(), "max_ticks": ticks, "score_target": 10**9})
    rng = random.Random(seed)
    state, _ = new_game(config, seed)
    started = time.perf_counter()
    while not state.finished:
        actions = {
            s.id: rng.choice(legal_moves(s.heading))
            for s in state.snakes
            if s.alive and s.heading is not None
        }
        state, _ = step(state, actions)
    return ticks / (time.perf_counter() - started)


def run_bench(config: GameConfig, ticks: int, seed: int, names: Sequence[str]) -> str:
    capped = GameConfig.from_dict({**config.to_dict(), "max_ticks": ticks, "score_target": 10**9})
    engine_rate = engine_ticks_per_second(config, ticks, seed)
    match = Match([make_policy(n) for n in names], seed, capped)
    started = time.perf_counter()
    result = match.run()
    match_rate = result.ticks / (time.perf_counter() - started)
    kills = sum(s.kills for s in result.standings)
    deaths = sum(s.deaths for s in result.standings)
    return "\n".join(
        [
            f"python {platform.python_version()} on {platform.machine()}, "
            f"{config.width}x{config.height}, {config.num_snakes} snakes x {config.snake_length}",
            f"engine only:         {engine_rate:>10,.0f} ticks/s",
            f"match ({','.join(sorted(set(names)))}): {match_rate:>10,.0f} ticks/s",
            f"kills per 1,000 ticks (all snakes): {1000 * kills / result.ticks:.3f}",
            f"deaths per 1,000 ticks (all snakes): {1000 * deaths / result.ticks:.3f}",
        ]
    )
