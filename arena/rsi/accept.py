"""The default acceptance rule, ``PairedBootstrapRule`` (phase 3 spec, section 5).

A candidate is accepted only if it never failed, its dev mean paired difference is above
zero, and on holdout its mean is at least ``min_rel_gain`` better, the paired bootstrap
interval of the mean difference lies above zero, and no guard metric got worse by more
than its tolerance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from arena.rsi.types import Decision, PairedResult


@dataclass(frozen=True)
class GuardMetric:
    """A secondary metric that may not get worse by more than ``tolerance`` (relative).

    With ``higher_is_worse`` (deaths, say) the candidate's value may be at most
    ``champion * (1 + tolerance) + slack``; otherwise at least
    ``champion * (1 - tolerance) - slack``. ``slack`` keeps a zero baseline from
    forbidding any change at all.
    """

    name: str
    tolerance: float
    higher_is_worse: bool = True
    slack: float = 0.0

    def violated(self, cand: float, champ: float) -> bool:
        if self.higher_is_worse:
            return cand > champ * (1 + self.tolerance) + self.slack
        return cand < champ * (1 - self.tolerance) - self.slack

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


def _pct(x: float) -> str:
    return f"{x:+.1%}" if np.isfinite(x) else ("+inf" if x > 0 else "-inf")
