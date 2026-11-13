"""The default acceptance rule, ``PairedBootstrapRule`` (phase 3 spec, section 5).

A candidate is accepted only if it never failed, its dev mean paired difference is above
zero, and on holdout its mean is at least ``min_rel_gain`` better, the paired bootstrap
interval of the mean difference lies above zero, and no guard metric got worse by more
than its tolerance.

``SequentialPairedRule`` is an opt-in alternative that spends evaluation episodes in
stages: it screens dev in chunks and stops a clearly worse candidate early (racing), and
it tests holdout at a few planned looks with an O'Brien-Fleming-type alpha-spending
boundary, so a clear winner is accepted early and a hopeless one is dropped early while
the false-accept probability per candidate stays at most ``alpha``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any, Literal

import numpy as np

from arena.rsi.types import Decision, PairedResult


@dataclass(frozen=True)
class GuardMetric:
    """A secondary metric that may not get worse by more than ``tolerance`` (relative).

    With ``higher_is_worse`` (deaths, say) the candidate's value may be at most
    ``champion + |champion| * tolerance + slack``; otherwise at least
    ``champion - |champion| * tolerance - slack``. ``slack`` keeps a zero baseline from
    forbidding any change at all.
    """

    name: str
    tolerance: float
    higher_is_worse: bool = True
    slack: float = 0.0

    def violated(self, cand: float, champ: float) -> bool:
        margin = abs(champ) * self.tolerance + self.slack
        if self.higher_is_worse:
            return cand > champ + margin
        return cand < champ - margin

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tolerance": self.tolerance,
            "higher_is_worse": self.higher_is_worse,
            "slack": self.slack,
        }


def bootstrap_ci(
    diffs: np.ndarray, rng: np.random.Generator, resamples: int = 10_000, level: float = 0.95
) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean of paired differences."""
    n = len(diffs)
    if n == 0:
        return 0.0, 0.0
    means = np.empty(resamples)
    chunk = max(1, 2_000_000 // n)
    for start in range(0, resamples, chunk):
        stop = min(resamples, start + chunk)
        idx = rng.integers(0, n, size=(stop - start, n))
        means[start:stop] = diffs[idx].mean(axis=1)
    tail = (1 - level) / 2
    lo, hi = np.quantile(means, [tail, 1 - tail])
    return float(lo), float(hi)


def relative_gain(mean_cand: float, mean_champ: float) -> float:
    """(cand - champ) / |champ|; infinite when the champion scores exactly zero."""
    diff = mean_cand - mean_champ
    if mean_champ == 0:
        return float("inf") if diff > 0 else (float("-inf") if diff < 0 else 0.0)
    return diff / abs(mean_champ)


@dataclass(frozen=True)
class PairedBootstrapRule:
    min_rel_gain: float = 0.02
    resamples: int = 10_000
    level: float = 0.95
    guards: Sequence[GuardMetric] = ()
    allow_extension: bool = True

    def passes_dev(self, dev: PairedResult) -> Decision | None:
        """None if the candidate may go on to holdout, else the rejection."""
        stats = {"dev": dev.summary()}
        if dev.failures:
            return Decision(False, "dev", f"{dev.failures} failures on dev", stats)
        if not dev.mean_diff > 0:
            return Decision(
                False, "dev", f"dev mean difference {dev.mean_diff:+.4g} is not above 0", stats
            )
        return None

    def _numbers(self, holdout: PairedResult, rng: np.random.Generator) -> dict[str, Any]:
        lo, hi = bootstrap_ci(holdout.diffs, rng, self.resamples, self.level)
        gain = relative_gain(holdout.mean_a, holdout.mean_b)
        return {**holdout.summary(), "rel_gain": gain, "ci": [lo, hi]}

    def wants_extension(self, holdout: PairedResult, rng: np.random.Generator) -> bool:
        """One more holdout sample when the mean looks good but the interval straddles 0."""
        if not self.allow_extension or holdout.failures:
            return False
        h = self._numbers(holdout, rng)
        return bool(h["rel_gain"] >= self.min_rel_gain and h["ci"][0] <= 0 < h["ci"][1])

    def decide(
        self,
        dev: PairedResult,
        holdout: PairedResult,
        rng: np.random.Generator,
        extended: bool = False,
    ) -> Decision:
        early = self.passes_dev(dev)
        if early is not None:
            return early
        h = self._numbers(holdout, rng)
        guards = holdout.guards()
        broken = [g.name for g in self.guards if g.name in guards and g.violated(*guards[g.name])]
        missing = [g.name for g in self.guards if g.name not in guards]
        stats: dict[str, Any] = {
            "dev": dev.summary(),
            "holdout": {**h, "extended": extended},
            "guards": {k: list(v) for k, v in guards.items()},
        }
        lo, hi = h["ci"]
        tail = f"gain {_pct(h['rel_gain'])}, {self.level:.0%} CI [{lo:+.4g}, {hi:+.4g}]"
        if holdout.failures:
            return Decision(False, "holdout", f"{holdout.failures} failures on holdout", stats)
        if missing:
            return Decision(False, "holdout", f"guard metrics not reported: {missing}", stats)
        if h["rel_gain"] < self.min_rel_gain:
            why = f"holdout {tail}: below the {self.min_rel_gain:.0%} minimum gain"
            return Decision(False, "holdout", why, stats)
        if not lo > 0:
            return Decision(False, "holdout", f"holdout {tail}: interval reaches 0", stats)
        if broken:
            return Decision(False, "holdout", f"holdout {tail}; guard worse: {broken}", stats)
        return Decision(True, "holdout", f"accepted: holdout {tail}", stats)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": "PairedBootstrapRule",
            "min_rel_gain": self.min_rel_gain,
            "resamples": self.resamples,
            "level": self.level,
            "guards": [g.to_dict() for g in self.guards],
            "allow_extension": self.allow_extension,
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> PairedBootstrapRule:
        return PairedBootstrapRule(
            d["min_rel_gain"],
            d["resamples"],
            d["level"],
            tuple(GuardMetric(**g) for g in d["guards"]),
            d["allow_extension"],
        )


_NORMAL = NormalDist()


def obrien_fleming_spending(alpha: float, fractions: Sequence[float]) -> tuple[float, ...]:
    """Cumulative one-sided error spent by each information fraction (Lan & DeMets 1983).

    ``alpha(t) = 2 (1 - Phi(z_{1 - alpha/2} / sqrt(t)))`` spends almost nothing at early
    looks and nearly all of ``alpha`` at the last one (``t = 1``).
    """
    z = _NORMAL.inv_cdf(1 - alpha / 2)
    return tuple(min(alpha, 2 * (1 - _NORMAL.cdf(z / math.sqrt(t)))) for t in fractions)


def look_boundaries(alpha: float, fractions: Sequence[float]) -> tuple[float, ...]:
    """z boundaries, one per look, whose one-sided error rates sum to at most ``alpha``.

    Each look gets the increment of the O'Brien-Fleming-type spending function and the
    looks are combined with a union bound, so the guarantee needs no assumption about how
    the looks are correlated (it is slightly conservative because of that).
    """
    spent = obrien_fleming_spending(alpha, fractions)
    steps = [b - a for a, b in zip((0.0, *spent), spent, strict=False)]
    return tuple(_NORMAL.inv_cdf(1 - max(step, 1e-15)) for step in steps)


def z_score(diffs: np.ndarray) -> float:
    """Mean paired difference over its standard error (+-inf when every pair is equal)."""
    n = len(diffs)
    if n == 0:
        return 0.0
    mean = float(np.mean(diffs))
    sd = float(np.std(diffs, ddof=1)) if n > 1 else 0.0
    if sd == 0.0:
        return math.copysign(math.inf, mean) if mean else 0.0
    return mean / (sd / math.sqrt(n))


def _schedule(total: int, fractions: Sequence[float], min_pairs: int) -> tuple[int, ...]:
    looks = sorted({min(total, max(min_pairs, round(f * total))) for f in fractions} | {total})
    return tuple(n for n in looks if n > 0)


DevVerdict = Literal["pass", "stop"]


@dataclass(frozen=True)
class SequentialPairedRule:
    """Group-sequential paired test with early stopping on dev and on holdout (opt-in).

    Dev: the candidate's dev slice is played in chunks at ``dev_fractions`` of
    ``dev_pairs``. After each chunk (from ``min_pairs`` pairs on) it stops when the paired
    z statistic is below ``dev_futility_z`` (clearly worse: rejected) or at least
    ``dev_pass_z`` (clearly better: straight to holdout). Dev never decides acceptance,
    so stopping it early cannot raise the false-accept rate.

    Holdout: the decision seeds plus the extension seeds form one sample of at most
    ``2 * holdout_pairs`` pairs, played at the looks ``holdout_fractions``. At look ``k``
    the candidate is accepted when ``z >= c_k`` (and the relative gain, guard and
    failure checks pass as in ``PairedBootstrapRule``), rejected for futility when
    ``z < futility_z``, and otherwise played on. The ``c_k`` come from
    ``look_boundaries(alpha, fractions)``, so a candidate that is truly no better is
    accepted with probability at most ``alpha`` (normal approximation). Futility stops
    only ever reject, so they never add false accepts.
    """

    min_rel_gain: float = 0.02
    alpha: float = 0.025
    holdout_fractions: tuple[float, ...] = (0.25, 0.5, 1.0)
    dev_fractions: tuple[float, ...] = (0.25, 0.5, 1.0)
    futility_z: float = 0.0
    dev_futility_z: float = 0.0
    dev_pass_z: float | None = 3.0
    min_pairs: int = 20
    guards: Sequence[GuardMetric] = ()
    use_extension: bool = True

    def __post_init__(self) -> None:
        for fractions in (self.holdout_fractions, self.dev_fractions):
            if not fractions or any(not 0 < f <= 1 for f in fractions) or max(fractions) != 1:
                raise ValueError("look fractions must lie in (0, 1] and end at 1")
        if not 0 < self.alpha < 0.5:
            raise ValueError("alpha must lie in (0, 0.5)")

    # -- dev ----------------------------------------------------------------------

    def dev_looks(self, pairs: int) -> tuple[int, ...]:
        return _schedule(pairs, self.dev_fractions, self.min_pairs)

    def dev_interim(self, dev: PairedResult) -> DevVerdict | None:
        """``stop`` (reject now), ``pass`` (go to holdout now) or None (play on)."""
        if dev.failures:
            return "stop"
        if dev.n < self.min_pairs:
            return None
        z = z_score(dev.diffs)
        if z < self.dev_futility_z:
            return "stop"
        if self.dev_pass_z is not None and z >= self.dev_pass_z and dev.mean_diff > 0:
            return "pass"
        return None

    def passes_dev(self, dev: PairedResult) -> Decision | None:
        return _DEV_SCREEN.passes_dev(dev)

    # -- holdout ------------------------------------------------------------------

    def holdout_looks(self, decision_pairs: int, extension_pairs: int) -> tuple[int, ...]:
        total = decision_pairs + (extension_pairs if self.use_extension else 0)
        return _schedule(total, self.holdout_fractions, self.min_pairs)

    def wants_extension(self, holdout: PairedResult, rng: np.random.Generator) -> bool:
        return False

    def decide_at(
        self,
        dev: PairedResult,
        holdout: PairedResult,
        looks: Sequence[int],
        rng: np.random.Generator | None = None,
    ) -> Decision | None:
        """The verdict after ``holdout.n`` pairs (one of ``looks``), or None to play on."""
        early = self.passes_dev(dev)
        if early is not None:
            return early
        if holdout.n not in looks:
            raise ValueError(f"{holdout.n} pairs is not one of the planned looks {list(looks)}")
        k = list(looks).index(holdout.n)
        last = k == len(looks) - 1
        bound = look_boundaries(self.alpha, [n / looks[-1] for n in looks])[k]
        z = z_score(holdout.diffs)
        sd = float(np.std(holdout.diffs, ddof=1)) if holdout.n > 1 else 0.0
        se = sd / math.sqrt(holdout.n) if holdout.n else 0.0
        mean = holdout.mean_diff
        gain = relative_gain(holdout.mean_a, holdout.mean_b)
        guards = holdout.guards()
        broken = [g.name for g in self.guards if g.name in guards and g.violated(*guards[g.name])]
        missing = [g.name for g in self.guards if g.name not in guards]
        h: dict[str, Any] = {
            **holdout.summary(),
            "rel_gain": gain,
            "ci": [mean - bound * se, mean + bound * se],
            "z": z,
            "boundary": bound,
            "look": k + 1,
            "looks": list(looks),
        }
        stats: dict[str, Any] = {
            "dev": dev.summary(),
            "holdout": h,
            "guards": {name: list(v) for name, v in guards.items()},
        }
        tail = f"look {k + 1}/{len(looks)}, {holdout.n} pairs, gain {_pct(gain)}, z {z:+.3g}"
        if holdout.failures:
            return Decision(False, "holdout", f"{holdout.failures} failures on holdout", stats)
        if missing:
            return Decision(False, "holdout", f"guard metrics not reported: {missing}", stats)
        if z >= bound and gain >= self.min_rel_gain and not broken:
            h["stopped"] = "efficacy"
            return Decision(True, "holdout", f"accepted: holdout {tail} >= {bound:.3g}", stats)
        if last:
            h["stopped"] = "final"
            if broken:
                why = f"guard worse: {broken}"
            elif gain < self.min_rel_gain:
                why = f"below the {self.min_rel_gain:.0%} minimum gain"
            else:
                why = f"z below the boundary {bound:.3g}"
            return Decision(False, "holdout", f"holdout {tail}: {why}", stats)
        if z < self.futility_z:
            h["stopped"] = "futility"
            why = f"holdout {tail}: stopped for futility (z < {self.futility_z:g})"
            return Decision(False, "holdout", why, stats)
        return None

    def decide(
        self,
        dev: PairedResult,
        holdout: PairedResult,
        rng: np.random.Generator,
        extended: bool = False,
    ) -> Decision:
        """A single-look decision on ``holdout`` (all of ``alpha`` at one look)."""
        decision = self.decide_at(dev, holdout, (holdout.n,), rng)
        assert decision is not None
        return decision

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": "SequentialPairedRule",
            "min_rel_gain": self.min_rel_gain,
            "alpha": self.alpha,
            "holdout_fractions": list(self.holdout_fractions),
            "dev_fractions": list(self.dev_fractions),
            "futility_z": self.futility_z,
            "dev_futility_z": self.dev_futility_z,
            "dev_pass_z": self.dev_pass_z,
            "min_pairs": self.min_pairs,
            "guards": [g.to_dict() for g in self.guards],
            "use_extension": self.use_extension,
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> SequentialPairedRule:
        return SequentialPairedRule(
            d["min_rel_gain"],
            d["alpha"],
            tuple(d["holdout_fractions"]),
            tuple(d["dev_fractions"]),
            d["futility_z"],
            d["dev_futility_z"],
            d["dev_pass_z"],
            d["min_pairs"],
            tuple(GuardMetric(**g) for g in d["guards"]),
            d["use_extension"],
        )


_DEV_SCREEN = PairedBootstrapRule()


def _pct(x: float) -> str:
    return f"{x:+.1%}" if np.isfinite(x) else ("+inf" if x > 0 else "-inf")
