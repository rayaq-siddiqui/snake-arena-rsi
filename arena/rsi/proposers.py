"""Built-in proposers (phase 3 spec, section 6).

All of them work in a normalised [0, 1] space per parameter (log-spaced where declared)
and map back through ``ParamSpec.from_unit``, which clips to bounds and rounds integers,
so every proposal is valid by construction. A proposer's self-adaptation lives in
``state()``, which the loop checkpoints so a resumed run proposes exactly the same.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from arena.rsi.types import Candidate, Feedback, History, ParamSpec, Proposer


def to_unit(params: Mapping[str, float], space: Sequence[ParamSpec]) -> np.ndarray:
    return np.array([p.to_unit(params[p.name]) for p in space], dtype=float)


def from_unit(u: np.ndarray, space: Sequence[ParamSpec]) -> dict[str, float]:
    return {p.name: p.from_unit(float(x)) for p, x in zip(space, u, strict=True)}


def describe_change(
    old: Mapping[str, float], new: Mapping[str, float], space: Sequence[ParamSpec]
) -> str:
    parts = [
        f"{p.name} {a}->{b}"
        for p in space
        if (a := f"{old[p.name]:.4g}") != (b := f"{new[p.name]:.4g}")
    ]
    return ", ".join(parts) if parts else "no change"


def _child(
    name: str, champion: Candidate, params: dict[str, float], history: History, note: str
) -> Candidate:
    return Candidate.make(params, champion.id, history.generation, name, note)


class RandomRestart:
    """Sample a fresh point uniformly: the control every real method must beat."""

    name = "random_restart"
    batch = 1

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        params = from_unit(rng.random(len(space)), space)
        return _child(self.name, champion, params, history, "uniform random point")

    def observe(self, feedback: Sequence[Feedback]) -> None:
        pass

    def state(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: Mapping[str, Any]) -> None:
        pass


class GaussianHillClimb:
    """Perturb 1-3 parameters with N(0, sigma) in normalised space.

    Self-adaptation: the 1/5th success rule (sigma x1.5 after an accept, x0.9 after a
    reject, kept within [sigma_min, sigma_max]), and parameters whose changes were
    accepted get picked more often (weight x1.5 on accept, decaying back toward 1).
    """

    name = "gaussian_hill_climb"
    batch = 1

    def __init__(
        self,
        sigma: float = 0.15,
        sigma_min: float = 0.01,
        sigma_max: float = 0.5,
        grow: float = 1.5,
        shrink: float = 0.9,
        max_params: int = 3,
    ) -> None:
        self.sigma = sigma
        self.sigma_min, self.sigma_max = sigma_min, sigma_max
        self.grow, self.shrink = grow, shrink
        self.max_params = max_params
        self.weights: dict[str, float] = {}
        self._touched: dict[str, list[str]] = {}

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        names = [p.name for p in space]
        w = np.array([self.weights.get(n, 1.0) for n in names])
        k = int(rng.integers(1, min(self.max_params, len(space)) + 1))
        picks = rng.choice(len(space), size=k, replace=False, p=w / w.sum())
        u = to_unit(champion.params, space)
        for i in picks:
            u[i] += rng.normal(0.0, self.sigma)
        params = from_unit(u, space)
        note = f"sigma {self.sigma:.3g}: " + describe_change(champion.params, params, space)
        cand = _child(self.name, champion, params, history, note)
        self._touched[cand.id] = sorted(names[int(i)] for i in picks)
        return cand

    def observe(self, feedback: Sequence[Feedback]) -> None:
        for f in feedback:
            touched = self._touched.pop(f.candidate.id, [])
            if f.stage == "validate":
                continue
            factor = self.grow if f.accepted else self.shrink
            self.sigma = min(self.sigma_max, max(self.sigma_min, self.sigma * factor))
            for n in list(self.weights):
                self.weights[n] = 1.0 + 0.9 * (self.weights[n] - 1.0)
            if f.accepted:
                for n in touched:
                    self.weights[n] = self.weights.get(n, 1.0) * 1.5
        self._touched.clear()

    def state(self) -> dict[str, Any]:
        return {"sigma": self.sigma, "weights": dict(sorted(self.weights.items()))}

    def load_state(self, state: Mapping[str, Any]) -> None:
        self.sigma = float(state["sigma"])
        self.weights = {k: float(v) for k, v in state["weights"].items()}


class CoordinateSearch:
    """Try +delta / -delta on one parameter at a time, cycling through all of them.

    Self-adaptation: delta halves after a full cycle with no accept. After an accept the
    same move is tried again.
    """

    name = "coordinate_search"
    batch = 1

    def __init__(self, delta: float = 0.25, delta_min: float = 0.005) -> None:
        self.delta = delta
        self.delta_min = delta_min
        self.position = 0
        self.cycle_accepted = False
        self._space_size = 0

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        moves = 2 * len(space)
        i, sign = divmod(self.position % moves, 2)
        u = to_unit(champion.params, space)
        u[i] += self.delta if sign == 0 else -self.delta
        params = from_unit(u, space)
        note = f"delta {self.delta:.3g}: " + describe_change(champion.params, params, space)
        self._space_size = len(space)
        return _child(self.name, champion, params, history, note)

    def observe(self, feedback: Sequence[Feedback]) -> None:
        for f in feedback:
            if f.accepted:
                self.cycle_accepted = True
                continue
            self.position += 1
            if self.position % (2 * self._space_size) == 0:
                if not self.cycle_accepted:
                    self.delta = max(self.delta_min, self.delta / 2)
                self.cycle_accepted = False

    def state(self) -> dict[str, Any]:
        return {
            "delta": self.delta,
            "position": self.position,
            "cycle_accepted": self.cycle_accepted,
            "space_size": self._space_size,
        }

    def load_state(self, state: Mapping[str, Any]) -> None:
        self.delta = float(state["delta"])
        self.position = int(state["position"])
        self.cycle_accepted = bool(state["cycle_accepted"])
        self._space_size = int(state["space_size"])


class CrossEntropy:
    """Keep a Gaussian over normalised parameters, sample ``batch`` per generation on dev,
    and refit mean and spread toward the ``elite`` best by dev mean difference."""

    name = "cross_entropy"

    def __init__(
        self,
        batch: int = 6,
        elite: int = 2,
        std: float = 0.2,
        std_min: float = 0.02,
        rate: float = 0.7,
    ) -> None:
        self.batch = batch
        self.elite = elite
        self.rate = rate
        self.std0, self.std_min = std, std_min
        self.mean: list[float] | None = None
        self.std: list[float] | None = None
        self._units: dict[str, list[float]] = {}

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        if self.mean is None or self.std is None:
            self.mean = to_unit(champion.params, space).tolist()
            self.std = [self.std0] * len(space)
        u = np.clip(rng.normal(self.mean, self.std), 0.0, 1.0)
        params = from_unit(u, space)
        note = "sample: " + describe_change(champion.params, params, space)
        cand = _child(self.name, champion, params, history, note)
        self._units[cand.id] = to_unit(params, space).tolist()
        return cand

    def observe(self, feedback: Sequence[Feedback]) -> None:
        scored = [
            (f.dev.mean_diff, self._units[f.candidate.id])
            for f in feedback
            if f.dev is not None and f.candidate.id in self._units
        ]
        self._units.clear()
        if not scored or self.mean is None or self.std is None:
            return
        scored.sort(key=lambda t: -t[0])
        elite = np.array([u for _, u in scored[: self.elite]])
        a = self.rate
        mean = (1 - a) * np.array(self.mean) + a * elite.mean(axis=0)
        spread = elite.std(axis=0) if len(elite) > 1 else np.zeros(len(self.mean))
        std = np.maximum(self.std_min, (1 - a) * np.array(self.std) + a * spread)
        self.mean, self.std = mean.tolist(), std.tolist()

    def state(self) -> dict[str, Any]:
        return {"mean": self.mean, "std": self.std}

    def load_state(self, state: Mapping[str, Any]) -> None:
        self.mean = None if state["mean"] is None else [float(x) for x in state["mean"]]
        self.std = None if state["std"] is None else [float(x) for x in state["std"]]


class ArchiveCrossover:
    """Mix the parameters of two archive members, then mutate lightly.

    Parent choice favours later archive members: each accepted candidate beat the
    champion before it, so a later member has beaten more of the archive. With fewer than
    two members it just mutates the champion.
    """

    name = "archive_crossover"
    batch = 1

    def __init__(self, sigma: float = 0.05) -> None:
        self.sigma = sigma

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        members = list(history.archive)
        if len(members) >= 2:
            rank = np.arange(1, len(members) + 1, dtype=float)
            i, j = rng.choice(len(members), size=2, replace=False, p=rank / rank.sum())
            a, b = members[int(i)], members[int(j)]
            mask = rng.random(len(space)) < 0.5
            u = np.where(mask, to_unit(a.params, space), to_unit(b.params, space))
            source = f"cross {a.id[:6]} x {b.id[:6]}"
        else:
            u = to_unit(champion.params, space)
            source = "mutate champion"
        u = u + rng.normal(0.0, self.sigma, len(space))
        params = from_unit(u, space)
        note = f"{source}: " + describe_change(champion.params, params, space)
        return _child(self.name, champion, params, history, note)

    def observe(self, feedback: Sequence[Feedback]) -> None:
        pass

    def state(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: Mapping[str, Any]) -> None:
        pass


PROPOSERS: dict[str, Callable[..., Proposer]] = {
    p.name: p
    for p in (RandomRestart, GaussianHillClimb, CoordinateSearch, CrossEntropy, ArchiveCrossover)
}


def make_proposer(name: str, **options: Any) -> Proposer:
    if name not in PROPOSERS:
        raise ValueError(f"unknown proposer {name!r}; choose from {', '.join(PROPOSERS)}")
    return PROPOSERS[name](**options)
