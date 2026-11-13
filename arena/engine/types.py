"""Immutable data types shared by the engine, the policies and the simulator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, ClassVar, Literal

Direction = Literal["UP", "DOWN", "LEFT", "RIGHT"]
SnakeId = str
Cell = tuple[int, int]

DIRECTIONS: tuple[Direction, ...] = ("UP", "RIGHT", "DOWN", "LEFT")
DELTAS: dict[Direction, Cell] = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
OPPOSITE: dict[Direction, Direction] = {
    "UP": "DOWN",
    "DOWN": "UP",
    "LEFT": "RIGHT",
    "RIGHT": "LEFT",
}

DeathCause = Literal["wall", "self", "body", "head_on", "head_swap"]
SELF_INFLICTED: frozenset[DeathCause] = frozenset({"wall", "self"})
"""Death causes that cost the victim ``GameConfig.self_death_penalty`` points."""
EndReason = Literal["score_target", "tick_cap"]


@dataclass(frozen=True)
class GameConfig:
    width: int = 150
    height: int = 150
    num_snakes: int = 5
    snake_length: int = 10
    respawn_delay: int = 10
    score_target: int = 100
    max_ticks: int = 100_000
    spawn_attempts: int = 100
    spawn_clearance: int = 2
    spawn_lookahead: int = 3
    self_death_penalty: int = 1

    def __post_init__(self) -> None:
        problems = []
        if not 3 <= self.snake_length <= 10:
            problems.append("snake_length must be in 3..10")
        if self.width < 10 or self.height < 10:
            problems.append("board must be at least 10 x 10")
        if self.width > 500 or self.height > 500:
            problems.append("board must be at most 500 x 500")
        if not 1 <= self.num_snakes <= 8:
            problems.append("num_snakes must be in 1..8")
        if self.respawn_delay < 1:
            problems.append("respawn_delay must be at least 1")
        if self.score_target < 1:
            problems.append("score_target must be at least 1")
        if self.max_ticks < 1:
            problems.append("max_ticks must be at least 1")
        if self.spawn_attempts < 0 or self.spawn_clearance < 0 or self.spawn_lookahead < 0:
            problems.append("spawn settings must be non-negative")
        if self.self_death_penalty < 0:
            problems.append("self_death_penalty must be non-negative")
        if problems:
            raise ValueError("; ".join(problems))

    @property
    def snake_ids(self) -> tuple[SnakeId, ...]:
        return tuple(f"s{i}" for i in range(self.num_snakes))

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameConfig:
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        values = {k: int(v) for k, v in data.items()}
        # Configs saved before the self-death penalty existed were played without it.
        values.setdefault("self_death_penalty", 0)
        return cls(**values)


@dataclass(frozen=True)
class SnakeState:
    id: SnakeId
    body: tuple[Cell, ...] = ()
    heading: Direction | None = None
    alive: bool = False
    life_id: int = 0
    kills: int = 0
    deaths: int = 0
    respawn_in: int = 0
    alive_ticks: int = 0
    life_ticks: int = 0
    penalty: int = 0

    @property
    def head(self) -> Cell:
        return self.body[0]

    @property
    def score(self) -> int:
        """Kills minus the points lost to self-inflicted deaths (wall or own body)."""
        return self.kills - self.penalty

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["body"] = [list(c) for c in self.body]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SnakeState:
        values = dict(data)
        values["body"] = tuple((int(x), int(y)) for x, y in data["body"])
        return cls(**values)


@dataclass(frozen=True)
class GameState:
    config: GameConfig
    snakes: tuple[SnakeState, ...]
    rng_state: int
    tick: int = 0
    finished: bool = False
    end_reason: EndReason | None = None

    def snake(self, snake_id: SnakeId) -> SnakeState:
        for s in self.snakes:
            if s.id == snake_id:
                return s
        raise KeyError(snake_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "snakes": [s.to_dict() for s in self.snakes],
            "rng_state": self.rng_state,
            "tick": self.tick,
            "finished": self.finished,
            "end_reason": self.end_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameState:
        return cls(
            config=GameConfig.from_dict(data["config"]),
            snakes=tuple(SnakeState.from_dict(s) for s in data["snakes"]),
            rng_state=int(data["rng_state"]),
            tick=int(data["tick"]),
            finished=bool(data["finished"]),
            end_reason=data["end_reason"],
        )


@dataclass(frozen=True)
class Event:
    kind: ClassVar[str] = "event"
    tick: int

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.kind}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, tuple):
                value = [list(v) if isinstance(v, tuple) else v for v in value]
            data[f.name] = value
        return data


@dataclass(frozen=True)
class Death(Event):
    kind: ClassVar[str] = "death"
    victim: SnakeId
    killer: SnakeId | None
    cause: DeathCause
    cell: Cell


@dataclass(frozen=True)
class Kill(Event):
    kind: ClassVar[str] = "kill"
    killer: SnakeId
    victim: SnakeId


@dataclass(frozen=True)
class Spawn(Event):
    kind: ClassVar[str] = "spawn"
    snake: SnakeId
    life_id: int
    cells: tuple[Cell, ...]
    heading: Direction


@dataclass(frozen=True)
class ActionFallback(Event):
    kind: ClassVar[str] = "action_fallback"
    snake: SnakeId
    reason: str


@dataclass(frozen=True)
class Standing:
    snake: SnakeId
    rank: int
    kills: int
    deaths: int
    alive_ticks: int
    penalty: int = 0

    @property
    def score(self) -> int:
        return self.kills - self.penalty

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "score": self.score}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Standing:
        return cls(**{k: v for k, v in data.items() if k != "score"})


@dataclass(frozen=True)
class MatchEnd(Event):
    kind: ClassVar[str] = "match_end"
    reason: EndReason
    standings: tuple[Standing, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.kind,
            "tick": self.tick,
            "reason": self.reason,
            "standings": [s.to_dict() for s in self.standings],
        }


def event_from_dict(data: dict[str, Any]) -> Event:
    kind = data["type"]
    values = {k: v for k, v in data.items() if k != "type"}
    if kind == "death":
        values["cell"] = tuple(values["cell"])
        return Death(**values)
    if kind == "kill":
        return Kill(**values)
    if kind == "spawn":
        values["cells"] = tuple(tuple(c) for c in values["cells"])
        return Spawn(**values)
    if kind == "action_fallback":
        return ActionFallback(**values)
    if kind == "match_end":
        values["standings"] = tuple(Standing.from_dict(s) for s in values["standings"])
        return MatchEnd(**values)
    raise ValueError(f"unknown event type: {kind}")


def as_direction(value: object) -> Direction | None:
    if isinstance(value, str) and value in DELTAS:
        return value
    return None
