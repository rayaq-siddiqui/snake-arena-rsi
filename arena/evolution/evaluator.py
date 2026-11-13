"""The snake evaluator (phase 4 spec, section 3).

For each seed the candidate and the champion each play one fixed-length episode in the
same seat, against the same opponents, with the same spawn seed, so the two games differ
only through the lineage's own choices. The opponents are drawn per seed from a frozen
``Context``: the other lineages' champions, their halls of fame, the hand-set reference
portfolio, or ``RandomSafe`` snakes.

Decision-time budgets are not enforced here: a wall-clock limit would make results
depend on machine load and break replay. ``bench`` measures decision time instead.
"""

from __future__ import annotations

import os
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from typing import Any, TypeVar

from arena.agents.registry import PERSONALITIES
from arena.engine import GameConfig
from arena.engine.rng import derive_seed
from arena.evolution.entrants import Entrant
from arena.rsi.types import Candidate, PairedResult
from arena.sim.match import Match
from arena.sim.personality_check import episode_config

MIXTURES = ("champions", "hall_of_fame", "reference", "random_safe")
GUARDS = ("deaths_per_1k_alive", "self_wall_deaths")


@dataclass(frozen=True)
class EvalSettings:
    width: int = 150
    height: int = 150
    ticks: int = 5000
    shares: tuple[float, float, float, float] = (0.50, 0.25, 0.15, 0.10)
    length: int = 10
    objective: str = "kills"
    """What a lineage maximises per 1,000 ticks: ``kills``, or ``score`` (kills minus the
    config's self-death penalty per wall or own-body death, the points that win matches)."""

    def __post_init__(self) -> None:
        if abs(sum(self.shares) - 1.0) > 1e-9 or min(self.shares) < 0:
            raise ValueError("mixture shares must be non-negative and sum to 1")
        if self.objective not in ("kills", "score"):
            raise ValueError("objective must be 'kills' or 'score'")

    def fitness(self, o: Outcome) -> float:
        points = o.kills
        if self.objective == "score":
            points -= self.config().self_death_penalty * o.self_wall
        return points * 1000 / self.ticks

    def config(self) -> GameConfig:
        return episode_config(self.width, self.height, self.ticks, self.length)

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "ticks": self.ticks,
            "length": self.length,
            "objective": self.objective,
            "shares": dict(zip(MIXTURES, self.shares, strict=True)),
        }


@dataclass(frozen=True)
class Context:
    """Everything a lineage's opponents are drawn from in one generation.

    Each tuple is indexed like ``PERSONALITIES``. ``halls[i]`` holds every champion
    lineage ``i`` has had so far, generation 0 included.
    """

    champions: tuple[Entrant, ...]
    halls: tuple[tuple[Entrant, ...], ...]
    reference: tuple[Entrant, ...]


@dataclass(frozen=True)
class Outcome:
    """One snake's numbers from one episode."""

    kills: int
    deaths: int
    alive_ticks: int
    self_wall: int
    fallbacks: int


def lineup(
    context: Context, me: int, seed: int, shares: Sequence[float] = (0.50, 0.25, 0.15, 0.10)
) -> tuple[int, str, list[Entrant]]:
    """(candidate seat, mixture name, the four opponents in seat order) for one seed."""
    count = len(PERSONALITIES)
    rng = random.Random(derive_seed(seed, "opponents"))
    r, mixture = rng.random(), MIXTURES[-1]
    edge = 0.0
    for name, share in zip(MIXTURES, shares, strict=True):
        edge += share
        if r < edge:
            mixture = name
            break
    opponents: list[Entrant] = []
    for j in range(count):
        if j == me:
            continue
        if mixture == "champions":
            opponents.append(context.champions[j])
        elif mixture == "hall_of_fame":
            hall = context.halls[j]
            opponents.append(hall[rng.randrange(len(hall))])
        elif mixture == "reference":
            opponents.append(context.reference[j])
        else:
            opponents.append(Entrant("random_safe", label="RandomSafe"))
    return seed % count, mixture, opponents


def play(config: GameConfig, entrants: Sequence[Entrant], seed: int, seat: int) -> Outcome:
    """Play one episode and return the numbers of the snake in ``seat``."""
    match = Match([e.build() for e in entrants], seed, config)
    result = match.run()
    sid = config.snake_ids[seat]
    standing = next(s for s in result.standings if s.snake == sid)
    causes = result.death_causes[sid]
    return Outcome(
        standing.kills,
        standing.deaths,
        standing.alive_ticks,
        causes.get("self", 0) + causes.get("wall", 0),
        match.fallbacks_by[sid],
    )


@dataclass(frozen=True)
class PairTask:
    config: GameConfig
    seed: int
    seat: int
    mixture: str
    a: Entrant
    b: Entrant
    opponents: tuple[Entrant, ...]


def play_pair(task: PairTask) -> tuple[Outcome, Outcome]:
    out = []
    for me in (task.a, task.b):
        entrants = list(task.opponents)
        entrants.insert(task.seat, me)
        out.append(play(task.config, entrants, task.seed, task.seat))
    return out[0], out[1]


T = TypeVar("T")
R = TypeVar("R")


class Workers:
    """A process pool whose results come back in input order, so the worker count never
    changes a result. One worker runs everything in this process."""

    def __init__(self, workers: int | None = None) -> None:
        self.count = max(1, workers if workers is not None else (os.cpu_count() or 1))
        self._pool: ProcessPoolExecutor | None = None

    def map(self, fn: Callable[[T], R], items: Iterable[T]) -> list[R]:
        items = list(items)
        if self.count == 1 or len(items) <= 1:
            return [fn(x) for x in items]
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=self.count)
        try:
            return list(self._pool.map(fn, items))
        except BrokenProcessPool:
            # A broken pool fails every later call; drop it so the next call starts afresh.
            self.close()
            raise

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(cancel_futures=True)
            self._pool = None

    def __enter__(self) -> Workers:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@dataclass
class SnakeEvaluator:
    """The phase 3 ``Evaluator`` for one lineage. The driver sets ``context`` before each
    generation; ``evaluate`` plays ``a`` and ``b`` in that lineage's place."""

    lineage: str
    settings: EvalSettings
    workers: Workers
    context: Context | None = None
    version: Mapping[str, int] = field(default_factory=dict)

    def entrant(self, c: Candidate) -> Entrant:
        return Entrant.personality(self.lineage, c.params, self.version.get(c.id, 0))

    def tasks(self, a: Candidate, b: Candidate, seeds: Sequence[int]) -> list[PairTask]:
        if self.context is None:
            raise RuntimeError("the evaluator has no context; set one before evaluating")
        me = PERSONALITIES.index(self.lineage)
        config = self.settings.config()
        ea, eb = self.entrant(a), self.entrant(b)
        out = []
        for seed in seeds:
            seat, mixture, opponents = lineup(self.context, me, seed, self.settings.shares)
            out.append(PairTask(config, seed, seat, mixture, ea, eb, tuple(opponents)))
        return out

    def evaluate(self, a: Candidate, b: Candidate, seeds: Sequence[int]) -> PairedResult:
        tasks = self.tasks(a, b, seeds)
        pairs = self.workers.map(play_pair, tasks)
        fit = self.settings.fitness
        score_a = tuple(fit(oa) for oa, _ in pairs)
        score_b = tuple(fit(ob) for _, ob in pairs)
        by_mixture: dict[str, list[float]] = {}
        for t, (oa, ob) in zip(tasks, pairs, strict=True):
            row = by_mixture.setdefault(t.mixture, [0, 0.0, 0.0])
            row[0] += 1
            row[1] += fit(oa)
            row[2] += fit(ob)
        return PairedResult(
            tuple(seeds),
            score_a,
            score_b,
            {
                "guards": {
                    "deaths_per_1k_alive": (
                        _death_rate(p[0] for p in pairs),
                        _death_rate(p[1] for p in pairs),
                    ),
                    "self_wall_deaths": (
                        _mean(p[0].self_wall for p in pairs),
                        _mean(p[1].self_wall for p in pairs),
                    ),
                },
                "champion_fallbacks": sum(ob.fallbacks for _, ob in pairs),
                "by_mixture": by_mixture,
            },
            sum(1 for oa, _ in pairs if oa.fallbacks),
        )


def _death_rate(outcomes: Iterable[Outcome]) -> float:
    deaths = alive = 0
    for o in outcomes:
        deaths += o.deaths
        alive += o.alive_ticks
    return 1000 * deaths / alive if alive else 0.0


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0
