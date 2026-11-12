"""Run a match: ask each policy for a move, step the engine, keep score."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from arena.agents.base import Observation, Policy, snake_views
from arena.engine import (
    ActionFallback,
    Death,
    Direction,
    Event,
    GameConfig,
    GameState,
    Kill,
    Standing,
    new_game,
    rank,
    step,
)
from arena.engine.rng import derive_seed
from arena.engine.types import as_direction


@dataclass(frozen=True)
class MatchResult:
    seed: int
    config: GameConfig
    policies: tuple[str, ...]
    ticks: int
    end_reason: str | None
    standings: tuple[Standing, ...]
    kill_matrix: dict[str, dict[str, int]]
    death_causes: dict[str, dict[str, int]]
    fallbacks: int

    @property
    def winner(self) -> str | None:
        top = [s for s in self.standings if s.rank == 1]
        return top[0].snake if len(top) == 1 else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "config": self.config.to_dict(),
            "policies": list(self.policies),
            "ticks": self.ticks,
            "end_reason": self.end_reason,
            "winner": self.winner,
            "standings": [s.to_dict() for s in self.standings],
            "kill_matrix": self.kill_matrix,
            "death_causes": self.death_causes,
            "fallbacks": self.fallbacks,
        }


@dataclass
class Match:
    """A match in progress. ``advance`` plays one tick; ``run`` plays to the end."""

    policies: Sequence[Policy]
    seed: int
    config: GameConfig = field(default_factory=GameConfig)
    record: bool = False
    move_budget_s: float | None = None

    def __post_init__(self) -> None:
        if len(self.policies) != self.config.num_snakes:
            raise ValueError(f"need {self.config.num_snakes} policies, got {len(self.policies)}")
        self.state: GameState
        self.state, events = new_game(self.config, self.seed)
        self.initial_state = self.state
        for sid, policy in zip(self.config.snake_ids, self.policies, strict=True):
            policy.reset(derive_seed(self.seed, "policy", sid))
        ids = self.config.snake_ids
        self.kill_matrix = {k: {v: 0 for v in ids} for k in ids}
        self.death_causes: dict[str, dict[str, int]] = {sid: {} for sid in ids}
        self.fallbacks = 0
        self.actions: list[list[Direction | None]] = []
        self.events: list[Event] = []
        self._account(events)

    @property
    def finished(self) -> bool:
        return self.state.finished

    def choose_actions(self) -> tuple[dict[str, Direction], list[Event]]:
        state = self.state
        views = snake_views(state)
        tick = state.tick + 1
        actions: dict[str, Direction] = {}
        fallbacks: list[Event] = []
        for snake, policy in zip(state.snakes, self.policies, strict=True):
            if not snake.alive:
                continue
            assert snake.heading is not None
            obs = Observation(state.tick, state.config.width, state.config.height, snake.id, views)
            reason = None
            started = time.perf_counter()
            try:
                choice = as_direction(policy.choose_action(obs))
            except Exception:
                choice, reason = None, "error"
            budget = self.move_budget_s
            if reason is None and budget is not None and time.perf_counter() - started > budget:
                choice, reason = None, "timeout"
            if choice is None:
                fallbacks.append(ActionFallback(tick, snake.id, reason or "invalid"))
                choice = snake.heading
            actions[snake.id] = choice
        return actions, fallbacks

    def advance(self) -> list[Event]:
        actions, fallbacks = self.choose_actions()
        if self.record:
            self.actions.append([actions.get(sid) for sid in self.config.snake_ids])
        self.state, events = step(self.state, actions)
        events = fallbacks + events
        self._account(events)
        return events

    def run(self) -> MatchResult:
        while not self.state.finished:
            self.advance()
        return self.result()

    def result(self) -> MatchResult:
        standings = rank(self.state.snakes)
        return MatchResult(
            seed=self.seed,
            config=self.config,
            policies=tuple(p.name for p in self.policies),
            ticks=self.state.tick,
            end_reason=self.state.end_reason,
            standings=standings,
            kill_matrix={k: dict(v) for k, v in self.kill_matrix.items()},
            death_causes={k: dict(v) for k, v in self.death_causes.items()},
            fallbacks=self.fallbacks,
        )

    def _account(self, events: list[Event]) -> None:
        for e in events:
            if isinstance(e, Kill):
                self.kill_matrix[e.killer][e.victim] += 1
            elif isinstance(e, Death):
                causes = self.death_causes[e.victim]
                causes[e.cause] = causes.get(e.cause, 0) + 1
            elif isinstance(e, ActionFallback):
                self.fallbacks += 1
        if self.record:
            self.events.extend(events)


def simulate_match(
    policies: Sequence[Policy],
    seed: int,
    config: GameConfig | None = None,
    move_budget_s: float | None = None,
) -> MatchResult:
    return Match(policies, seed, config or GameConfig(), move_budget_s=move_budget_s).run()
