"""Core types of the generic RSI loop (phase 3 spec, section 2).

Nothing here knows what is being improved: a problem is a list of ``ParamSpec`` plus an
``Evaluator`` that plays two candidates on the same seeds.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import numpy as np

Params = Mapping[str, float]


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: Literal["float", "int"]
    low: float
    high: float
    default: float
    scale: Literal["linear", "log"] = "linear"

    def __post_init__(self) -> None:
        if not self.low < self.high:
            raise ValueError(f"{self.name}: low must be below high")
        if not self.low <= self.default <= self.high:
            raise ValueError(
                f"{self.name}: default {self.default} outside [{self.low}, {self.high}]"
            )
        if self.scale == "log" and self.low <= 0:
            raise ValueError(f"{self.name}: a log-scale parameter needs low > 0")
        if self.kind == "int" and not (
            float(self.low).is_integer() and float(self.high).is_integer()
        ):
            raise ValueError(f"{self.name}: an int parameter needs integer bounds")

    def to_unit(self, value: float) -> float:
        """Map a value to [0, 1] (log-spaced for log-scale parameters)."""
        if self.scale == "log":
            lo, hi = math.log(self.low), math.log(self.high)
            return (math.log(value) - lo) / (hi - lo)
        return (value - self.low) / (self.high - self.low)

    def from_unit(self, u: float) -> float:
        """Map a unit-interval number back to a valid value: clipped, and rounded if int."""
        u = min(1.0, max(0.0, float(u)))
        if self.scale == "log":
            lo, hi = math.log(self.low), math.log(self.high)
            value = math.exp(lo + u * (hi - lo))
        else:
            value = self.low + u * (self.high - self.low)
        value = min(self.high, max(self.low, value))
        return float(round(value)) if self.kind == "int" else value

    def check(self, value: Any) -> str | None:
        """Why ``value`` is not valid for this parameter, or None if it is."""
        if isinstance(value, bool) or not isinstance(value, int | float):
            return f"{self.name}: {value!r} is not a number"
        if not math.isfinite(value):
            return f"{self.name}: {value!r} is not finite"
        if not self.low <= value <= self.high:
            return f"{self.name}: {value} outside [{self.low}, {self.high}]"
        if self.kind == "int" and not float(value).is_integer():
            return f"{self.name}: {value} is not an integer"
        return None


def defaults(space: Sequence[ParamSpec]) -> dict[str, float]:
    return {p.name: float(p.default) for p in space}


def validate(params: Params, space: Sequence[ParamSpec]) -> list[str]:
    """Every problem with ``params`` against ``space`` (empty if valid)."""
    names = {p.name for p in space}
    problems = [f"unknown parameter {n}" for n in sorted(set(params) - names)]
    problems += [f"missing parameter {n}" for n in sorted(names - set(params))]
    for p in space:
        if p.name in params and (why := p.check(params[p.name])):
            problems.append(why)
    return problems


def params_id(params: Params) -> str:
    """Content hash of a parameter set: equal values give equal ids."""
    canon = json.dumps({k: float(v) for k, v in sorted(params.items())}, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Candidate:
    id: str
    params: Mapping[str, float]
    parent_id: str | None
    generation: int
    proposer: str
    note: str

    @staticmethod
    def make(
        params: Params, parent_id: str | None, generation: int, proposer: str, note: str
    ) -> Candidate:
        values = {k: float(v) for k, v in params.items()}
        return Candidate(params_id(values), values, parent_id, generation, proposer, note)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "params": dict(self.params),
            "parent_id": self.parent_id,
            "generation": self.generation,
            "proposer": self.proposer,
            "note": self.note,
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> Candidate:
        return Candidate(
            d["id"], dict(d["params"]), d["parent_id"], d["generation"], d["proposer"], d["note"]
        )


@dataclass(frozen=True)
class PairedResult:
    """Candidate ``a`` and reference ``b`` played on the same seeds, one score each per seed.

    ``diagnostics`` holds secondary metrics. They never grade a candidate unless the
    acceptance rule declares them as guard metrics: ``diagnostics["guards"][name]`` is then
    ``(value for a, value for b)``.
    """

    seeds: tuple[int, ...]
    score_a: tuple[float, ...]
    score_b: tuple[float, ...]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    failures: int = 0

    def __post_init__(self) -> None:
        if not len(self.seeds) == len(self.score_a) == len(self.score_b):
            raise ValueError("a paired result needs one score per seed for each side")

    @property
    def n(self) -> int:
        return len(self.seeds)

    @property
    def diffs(self) -> np.ndarray:
        out: np.ndarray = np.asarray(self.score_a, dtype=float) - np.asarray(
            self.score_b, dtype=float
        )
        return out

    @property
    def mean_a(self) -> float:
        return float(np.mean(self.score_a)) if self.seeds else 0.0

    @property
    def mean_b(self) -> float:
        return float(np.mean(self.score_b)) if self.seeds else 0.0

    @property
    def mean_diff(self) -> float:
        return float(np.mean(self.diffs)) if self.seeds else 0.0

    def guards(self) -> dict[str, tuple[float, float]]:
        raw = self.diagnostics.get("guards", {})
        return {k: (float(v[0]), float(v[1])) for k, v in raw.items()}

    def extend(self, more: PairedResult) -> PairedResult:
        """This result plus ``more`` (guard values are averaged by sample size)."""
        guards: dict[str, tuple[float, float]] = {}
        mine, theirs = self.guards(), more.guards()
        total = self.n + more.n
        for k in mine.keys() & theirs.keys():
            guards[k] = (
                (mine[k][0] * self.n + theirs[k][0] * more.n) / total,
                (mine[k][1] * self.n + theirs[k][1] * more.n) / total,
            )
        return PairedResult(
            self.seeds + more.seeds,
            self.score_a + more.score_a,
            self.score_b + more.score_b,
            {"guards": guards} if guards else {},
            self.failures + more.failures,
        )

    def summary(self) -> dict[str, Any]:
        """Means and sizes only: what a generation record keeps."""
        return {
            "n": self.n,
            "mean_cand": self.mean_a,
            "mean_champ": self.mean_b,
            "diff": self.mean_diff,
            "failures": self.failures,
        }


@dataclass(frozen=True)
class Decision:
    """The acceptance rule's verdict on one candidate, with everything it was based on."""

    accept: bool
    stage: Literal["validate", "dev", "holdout"]
    rationale: str
    stats: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accept": self.accept,
            "stage": self.stage,
            "rationale": self.rationale,
            "stats": dict(self.stats),
        }


@dataclass(frozen=True)
class Feedback:
    """What a proposer learns about one of its candidates.

    Only dev results and whether the candidate was accepted: never holdout seeds or
    holdout numbers (phase 3 spec, section 4).
    """

    generation: int
    candidate: Candidate
    accepted: bool
    stage: Literal["validate", "dev", "screened", "holdout"]
    dev: PairedResult | None


@dataclass(frozen=True)
class History:
    """Everything a proposer may look at when proposing."""

    generation: int
    feedback: tuple[Feedback, ...]
    archive: tuple[Candidate, ...]


@dataclass(frozen=True)
class Budget:
    """Caps on a run. ``None`` means no cap."""

    generations: int | None = None
    episodes: int | None = None
    seconds: float | None = None
    tokens: int | None = None
    dollars: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generations": self.generations,
            "episodes": self.episodes,
            "seconds": self.seconds,
            "tokens": self.tokens,
            "dollars": self.dollars,
        }


class Proposer(Protocol):
    name: str
    batch: int

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate: ...

    def observe(self, feedback: Sequence[Feedback]) -> None: ...

    def state(self) -> dict[str, Any]: ...

    def load_state(self, state: Mapping[str, Any]) -> None: ...


class Evaluator(Protocol):
    def evaluate(self, a: Candidate, b: Candidate, seeds: Sequence[int]) -> PairedResult: ...


class AcceptanceRule(Protocol):
    def passes_dev(self, dev: PairedResult) -> Decision | None: ...

    def wants_extension(self, holdout: PairedResult, rng: np.random.Generator) -> bool: ...

    def decide(
        self,
        dev: PairedResult,
        holdout: PairedResult,
        rng: np.random.Generator,
        extended: bool = False,
    ) -> Decision: ...

    def to_dict(self) -> dict[str, Any]: ...
