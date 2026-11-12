"""Speed and kill-rate measurements (phase 1 spec, section 10)."""

from __future__ import annotations

import platform
import random
import time
from collections.abc import Sequence

from arena.agents import make_policy
from arena.agents.base import Observation, Policy, legal_moves
from arena.engine import Direction, GameConfig, new_game, step
from arena.sim.match import Match

MEDIAN_BUDGET_MS = 5.0
P99_BUDGET_MS = 20.0


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


class Timed:
    """Wraps a policy and records how long each decision takes, in milliseconds."""

    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        self.name = policy.name
        self.version = policy.version
        self.times: list[float] = []

    def reset(self, seed: int) -> None:
        self.policy.reset(seed)

    def choose_action(self, obs: Observation) -> Direction:
        started = time.perf_counter()
        try:
            return self.policy.choose_action(obs)
        finally:
            self.times.append(1000 * (time.perf_counter() - started))


def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else 0.0


def decision_times(
    config: GameConfig, ticks: int, seed: int, names: Sequence[str]
) -> dict[str, list[float]]:
    """Per-move decision times by policy name, from one match with the given lineup."""
    capped = GameConfig.from_dict({**config.to_dict(), "max_ticks": ticks, "score_target": 10**9})
    timed = [Timed(make_policy(n)) for n in names]
    Match(timed, seed, capped).run()
    out: dict[str, list[float]] = {}
    for t in timed:
        out.setdefault(t.name, []).extend(t.times)
    return out


def decision_report(times: dict[str, list[float]]) -> tuple[str, bool]:
    lines = [
        f"decision time per move (budget: median <= {MEDIAN_BUDGET_MS:g} ms, "
        f"p99 <= {P99_BUDGET_MS:g} ms)",
        f"  {'policy':<14}{'moves':>8}{'median ms':>11}{'p99 ms':>9}{'max ms':>9}  ok",
    ]
    ok_all = True
    for name, values in times.items():
        median, p99 = percentile(values, 0.5), percentile(values, 0.99)
        ok = median <= MEDIAN_BUDGET_MS and p99 <= P99_BUDGET_MS
        ok_all &= ok
        lines.append(
            f"  {name:<14}{len(values):>8,}{median:>11.3f}{p99:>9.3f}{max(values):>9.3f}  "
            f"{'yes' if ok else 'NO'}"
        )
    return "\n".join(lines), ok_all
