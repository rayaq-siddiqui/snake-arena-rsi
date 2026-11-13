"""Built-in proposers (phase 3 spec, section 6).

All of them work in a normalised [0, 1] space per parameter (log-spaced where declared)
and map back through ``ParamSpec.from_unit``, which clips to bounds and rounds integers,
so every proposal is valid by construction. A proposer's self-adaptation lives in
``state()``, which the loop checkpoints so a resumed run proposes exactly the same.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from arena.rsi.accept import z_score
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


class PopulationHillClimb:
    """PBT-style parallel hill climbers (Jaderberg et al. 2017, plan step 5.3).

    ``batch`` members each keep their own position and step size and propose one
    candidate per generation, so a generation screens ``batch`` candidates on dev.
    A member moves to its candidate when the candidate's dev score (its paired
    difference against the champion) is at least the member's current score. Then the
    population trains itself: the bottom ``exploit`` members copy the position, step
    size and score of a random top member ("exploit") and multiply the copied step size
    by 0.8 or 1.25 ("explore"). When a candidate is accepted the champion moves, so
    every score is shifted by that candidate's dev difference to stay comparable.
    """

    name = "pbt"

    def __init__(
        self,
        batch: int = 4,
        sigma: float = 0.15,
        sigma_min: float = 0.01,
        sigma_max: float = 0.5,
        exploit: int = 1,
        max_params: int = 3,
    ) -> None:
        if batch < 2 or not 1 <= exploit <= batch // 2:
            raise ValueError("pbt needs batch >= 2 and 1 <= exploit <= batch // 2")
        self.batch = batch
        self.sigma0, self.sigma_min, self.sigma_max = sigma, sigma_min, sigma_max
        self.exploit = exploit
        self.max_params = max_params
        self.members: list[dict[str, Any]] = []
        self._turn = 0
        self._pending: dict[str, tuple[int, list[float]]] = {}
        self._rng_draws: list[float] = []

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        if not self.members:
            start = to_unit(champion.params, space).tolist()
            self.members = [
                {"u": list(start), "sigma": self.sigma0, "score": 0.0} for _ in range(self.batch)
            ]
        i = self._turn % self.batch
        self._turn += 1
        member = self.members[i]
        u = np.array(member["u"], dtype=float)
        k = int(rng.integers(1, min(self.max_params, len(space)) + 1))
        for j in rng.choice(len(space), size=k, replace=False):
            u[j] += rng.normal(0.0, member["sigma"])
        params = from_unit(u, space)
        self._rng_draws.append(float(rng.random()))
        note = f"member {i} sigma {member['sigma']:.3g}: " + describe_change(
            champion.params, params, space
        )
        cand = _child(self.name, champion, params, history, note)
        self._pending[cand.id] = (i, to_unit(params, space).tolist())
        return cand

    def observe(self, feedback: Sequence[Feedback]) -> None:
        shift = 0.0
        for f in feedback:
            pending = self._pending.get(f.candidate.id)
            if pending is None or f.dev is None:
                continue
            i, u = pending
            member = self.members[i]
            if f.dev.mean_diff >= member["score"]:
                member["u"], member["score"] = u, f.dev.mean_diff
            if f.accepted:
                shift = f.dev.mean_diff
        draws, self._rng_draws = self._rng_draws, []
        self._pending.clear()
        self._turn = 0
        if not self.members or not draws:
            return
        for m in self.members:
            m["score"] -= shift
        order = sorted(range(self.batch), key=lambda j: (-self.members[j]["score"], j))
        top, bottom = order[: self.exploit], order[-self.exploit :]
        for n, j in enumerate(bottom):
            draw = draws[n % len(draws)]
            src = self.members[top[int(draw * len(top)) % len(top)]]
            factor = 1.25 if draw * 2 % 1 >= 0.5 else 0.8
            sigma = min(self.sigma_max, max(self.sigma_min, src["sigma"] * factor))
            self.members[j] = {"u": list(src["u"]), "sigma": sigma, "score": src["score"]}

    def state(self) -> dict[str, Any]:
        return {"members": [dict(m) for m in self.members]}

    def load_state(self, state: Mapping[str, Any]) -> None:
        self.members = [
            {
                "u": [float(x) for x in m["u"]],
                "sigma": float(m["sigma"]),
                "score": float(m["score"]),
            }
            for m in state["members"]
        ]


class OnePlusOneCMA:
    """The (1+1)-CMA-ES of Igel, Suttorp & Hansen (2006), with the active covariance
    update of Arnold & Hansen (2010), in normalised space.

    One candidate per generation: the champion plus ``sigma * A z``, where ``z`` is
    standard normal and ``A A^T = C``. Unlike ``GaussianHillClimb`` it moves every
    parameter at once and learns ``C``, so it can follow correlated or badly scaled
    directions (a ridge where two weights must rise together).

    Self-adaptation, all from what the proposer may see:

    - step size: a smoothed success rate ``p_succ`` (success = accepted) is pushed toward
      ``p_target`` = 2/11 by ``sigma *= exp((p_succ - p_target) / (d (1 - p_target)))``
      (Igel et al.'s improved 1/5th rule), with ``sigma`` kept in ``[sigma_min,
      sigma_max]``;
    - covariance: an accepted step feeds an evolution path ``p_c`` and a rank-one update
      of ``C``; with ``active``, a step whose dev z statistic is below ``bad_z`` (clearly
      worse) shrinks ``C`` along that direction.

    The step that is learned from is the one actually taken after clipping to bounds
    and rounding integers, so the update never learns a direction it did not try.
    """

    name = "cma_es"
    batch = 1
    max_condition = 1e6

    def __init__(
        self,
        sigma: float = 0.15,
        sigma_min: float = 0.005,
        sigma_max: float = 0.5,
        p_target: float = 2 / 11,
        active: bool = True,
        bad_z: float = -2.0,
    ) -> None:
        self.sigma0 = self.sigma = sigma
        self.sigma_min, self.sigma_max = sigma_min, sigma_max
        self.p_target = p_target
        self.p_succ = p_target
        self.active = active
        self.bad_z = bad_z
        self.cov: list[list[float]] | None = None
        self.path: list[float] | None = None
        self._steps: dict[str, list[float]] = {}

    def _factor(self, n: int) -> np.ndarray:
        if self.cov is None or len(self.cov) != n:
            self.cov = np.eye(n).tolist()
            self.path = [0.0] * n
        c = np.array(self.cov)
        try:
            factor: np.ndarray = np.linalg.cholesky(c)
        except np.linalg.LinAlgError:
            self.cov = np.eye(n).tolist()
            factor = np.eye(n)
        return factor

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        n = len(space)
        a = self._factor(n)
        u0 = to_unit(champion.params, space)
        u = u0 + self.sigma * (a @ rng.standard_normal(n))
        params = from_unit(u, space)
        note = f"sigma {self.sigma:.3g}: " + describe_change(champion.params, params, space)
        cand = _child(self.name, champion, params, history, note)
        self._steps[cand.id] = ((to_unit(params, space) - u0) / self.sigma).tolist()
        return cand

    def observe(self, feedback: Sequence[Feedback]) -> None:
        for f in feedback:
            step = self._steps.get(f.candidate.id)
            if step is None or f.stage in ("validate", "screened"):
                continue
            if self.cov is None or self.path is None:
                continue
            n = len(step)
            y = np.array(step)
            cov = np.array(self.cov)
            d = 1.0 + n / 2.0
            c_p, c_c, c_cov = 1 / 12, 2 / (n + 2), 2 / (n**2 + 6)
            self.p_succ = (1 - c_p) * self.p_succ + c_p * float(f.accepted)
            ratio = (self.p_succ - self.p_target) / (d * (1 - self.p_target))
            self.sigma = min(self.sigma_max, max(self.sigma_min, self.sigma * math.exp(ratio)))
            path = np.array(self.path)
            if f.accepted:
                if self.p_succ < 0.44:
                    path = (1 - c_c) * path + math.sqrt(c_c * (2 - c_c)) * y
                    cov = (1 - c_cov) * cov + c_cov * np.outer(path, path)
                else:
                    path = (1 - c_c) * path
                    cov = (1 - c_cov) * cov + c_cov * (np.outer(path, path) + c_c * (2 - c_c) * cov)
            elif self.active and f.dev is not None and z_score(f.dev.diffs) < self.bad_z:
                cov = self._shrink(cov, y, n)
            self.cov, self.path = cov.tolist(), path.tolist()
        self._steps.clear()

    @staticmethod
    def _shrink(cov: np.ndarray, y: np.ndarray, n: int) -> np.ndarray:
        """Arnold & Hansen's negative rank-one update, kept positive definite."""
        try:
            z = np.linalg.solve(np.linalg.cholesky(cov), y)
        except np.linalg.LinAlgError:
            return cov
        zz = float(z @ z)
        c_minus = 0.4 / (n**1.6 + 1)
        if zz > 1:
            c_minus = min(c_minus, 1 / (2 * zz - 1))
        out: np.ndarray = (1 + c_minus) * cov - c_minus * np.outer(y, y)
        try:
            np.linalg.cholesky(out)
        except np.linalg.LinAlgError:
            return cov
        # The same clipped step can repeat at a bound; without a cap C would collapse.
        if np.linalg.cond(out) > OnePlusOneCMA.max_condition:
            return cov
        return out

    def state(self) -> dict[str, Any]:
        return {
            "sigma": self.sigma,
            "p_succ": self.p_succ,
            "cov": self.cov,
            "path": self.path,
        }

    def load_state(self, state: Mapping[str, Any]) -> None:
        self.sigma = float(state["sigma"])
        self.p_succ = float(state["p_succ"])
        cov, path = state["cov"], state["path"]
        self.cov = None if cov is None else [[float(x) for x in row] for row in cov]
        self.path = None if path is None else [float(x) for x in path]


PROPOSERS: dict[str, Callable[..., Proposer]] = {
    p.name: p
    for p in (
        RandomRestart,
        GaussianHillClimb,
        CoordinateSearch,
        CrossEntropy,
        ArchiveCrossover,
        PopulationHillClimb,
        OnePlusOneCMA,
    )
}


def make_proposer(name: str, **options: Any) -> Proposer:
    """A built-in proposer by name; ``llm`` is the optional, opt-in ``LLMProposer``."""
    if name == "llm":
        from arena.rsi.llm import LLMProposer

        return LLMProposer(**options)
    if name == "harness":
        from arena.rsi.harness import AdaptiveHarness

        return AdaptiveHarness(**options)
    if name not in PROPOSERS:
        names = ", ".join([*PROPOSERS, "harness", "llm"])
        raise ValueError(f"unknown proposer {name!r}; choose from {names}")
    return PROPOSERS[name](**options)
