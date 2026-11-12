"""Small, seeded statistics helpers."""

from __future__ import annotations

import random
from collections.abc import Sequence


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def bootstrap_mean_ci(
    values: Sequence[float], resamples: int = 2000, level: float = 0.95, seed: int = 0
) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean. Seeded, so the same data gives the same CI."""
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(resamples))
    tail = (1 - level) / 2
    lo = means[int(tail * resamples)]
    hi = means[min(resamples - 1, int((1 - tail) * resamples))]
    return lo, hi
