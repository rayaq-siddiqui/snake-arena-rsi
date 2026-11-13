"""Toy problems that prove the loop works before any snake uses it (phase 3 spec, §10).

Each toy score is ``true score + shared noise + own noise``. The shared part depends only
on the seed, like a game layout that is easy or hard for everybody, so paired evaluation
cancels it. The own part depends on the seed and the candidate, like luck within a game.
"""

from __future__ import annotations

import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from arena.rsi.types import Candidate, PairedResult, ParamSpec


def _noise(problem_seed: int, seed: int, key: str) -> float:
    rng = np.random.default_rng([problem_seed, seed, zlib.crc32(key.encode())])
    return float(rng.standard_normal())


@dataclass
class NoisyQuadratic:
    """score = -||x - x*||^2 + noise, with x* drawn from ``problem_seed``; the best is 0."""

    dim: int = 5
    problem_seed: int = 0
    bound: float = 5.0
    shared_sd: float = 5.0
    noise_sd: float = 1.0
    optimum: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        rng = np.random.default_rng([self.problem_seed, zlib.crc32(b"optimum")])
        self.optimum = rng.uniform(-0.8 * self.bound, 0.8 * self.bound, self.dim)

    @property
    def space(self) -> tuple[ParamSpec, ...]:
        return tuple(
            ParamSpec(f"x{i}", "float", -self.bound, self.bound, 0.0) for i in range(self.dim)
        )

    def true_score(self, params: Mapping[str, float]) -> float:
        x = np.array([params[f"x{i}"] for i in range(self.dim)])
        return -float(np.sum((x - self.optimum) ** 2))

    def score(self, c: Candidate, seed: int) -> float:
        return (
            self.true_score(c.params)
            + self.shared_sd * _noise(self.problem_seed, seed, "shared")
            + self.noise_sd * _noise(self.problem_seed, seed, c.id)
        )

    def evaluate(self, a: Candidate, b: Candidate, seeds: Sequence[int]) -> PairedResult:
        return PairedResult(
            tuple(seeds),
            tuple(self.score(a, s) for s in seeds),
            tuple(self.score(b, s) for s in seeds),
        )


@dataclass
class PureNoise(NoisyQuadratic):
    """Every candidate has the same true score: any accept is luck."""

    level: float = -10.0

    def true_score(self, params: Mapping[str, float]) -> float:
        return self.level


@dataclass
class NoisyEllipsoid(NoisyQuadratic):
    """A rotated, badly scaled quadratic: score = -sum_i w_i (R (x - x*))_i^2 + noise.

    The weights ``w`` run geometrically from 1 to ``condition`` and are rescaled to
    average 1, and ``R`` is a random rotation from ``problem_seed``, so the best moves
    change several parameters together. Real policy weights often trade off like this
    (raise one, lower another); a method that only nudges one parameter at a time
    struggles here while one that learns a covariance should not.
    """

    condition: float = 100.0
    rotation: np.ndarray = field(init=False)
    weights: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        rng = np.random.default_rng([self.problem_seed, zlib.crc32(b"rotation")])
        q, r = np.linalg.qr(rng.standard_normal((self.dim, self.dim)))
        self.rotation = q * np.sign(np.diag(r))
        w = self.condition ** (np.arange(self.dim) / max(1, self.dim - 1))
        self.weights = w / w.mean()

    def true_score(self, params: Mapping[str, float]) -> float:
        x = np.array([params[f"x{i}"] for i in range(self.dim)])
        y = self.rotation @ (x - self.optimum)
        return -float(np.sum(self.weights * y**2))


@dataclass
class RareEvents(NoisyQuadratic):
    """Scores are rare event counts, like kills in a short game: Poisson draws.

    A candidate's true score is its expected count per episode,
    ``peak * exp(-||x - x*||^2 / (2 width^2))``, so most of the space scores close to
    zero. Each seed multiplies every candidate's rate by a shared gamma factor (an easy
    or hard layout; pairing removes part of it, not all) before the Poisson draw, which is
    the candidate's own luck. With ``flat`` every candidate has the rate ``peak``: the
    rare-event version of ``PureNoise``, for checking false accepts on sparse, discrete,
    mostly-zero differences.
    """

    peak: float = 1.0
    width: float = 3.0
    shape: float = 4.0
    flat: bool = False

    def true_score(self, params: Mapping[str, float]) -> float:
        if self.flat:
            return self.peak
        x = np.array([params[f"x{i}"] for i in range(self.dim)])
        return self.peak * float(np.exp(-np.sum((x - self.optimum) ** 2) / (2 * self.width**2)))

    def score(self, c: Candidate, seed: int) -> float:
        shared = np.random.default_rng([self.problem_seed, seed, zlib.crc32(b"layout")])
        factor = shared.gamma(self.shape, 1 / self.shape)
        own = np.random.default_rng([self.problem_seed, seed, zlib.crc32(c.id.encode())])
        return float(own.poisson(self.true_score(c.params) * factor))


@dataclass
class CrashingEvaluator:
    """Wraps a problem; candidates with ``x0 > threshold`` look far better but crash on a
    few seeds. They must never be accepted."""

    inner: NoisyQuadratic
    threshold: float = 0.0
    crash_rate: float = 0.05

    def bad(self, c: Candidate) -> bool:
        return c.params["x0"] > self.threshold

    def evaluate(self, a: Candidate, b: Candidate, seeds: Sequence[int]) -> PairedResult:
        r = self.inner.evaluate(a, b, seeds)
        if not self.bad(a):
            return r
        crashes = sum(
            1 for s in seeds if _noise(self.inner.problem_seed, s, "crash" + a.id) > 1.645
        )
        crashes = max(1, crashes) if seeds else 0
        boosted = tuple(x + 100.0 for x in r.score_a)
        return PairedResult(r.seeds, boosted, r.score_b, r.diagnostics, crashes)


@dataclass
class SpyEvaluator:
    """Records every seed list it is asked to play, to check who saw what."""

    inner: NoisyQuadratic
    calls: list[tuple[int, ...]] = field(default_factory=list)

    def evaluate(self, a: Candidate, b: Candidate, seeds: Sequence[int]) -> PairedResult:
        self.calls.append(tuple(seeds))
        return self.inner.evaluate(a, b, seeds)


PROBLEMS: dict[str, type[NoisyQuadratic]] = {
    "quadratic": NoisyQuadratic,
    "noise": PureNoise,
    "ellipsoid": NoisyEllipsoid,
    "rare": RareEvents,
}
