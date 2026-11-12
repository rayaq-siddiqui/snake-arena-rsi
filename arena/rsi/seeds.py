"""Seed pools that never mix (phase 3 spec, section 4) and seeded random streams.

``dev`` screens candidates (a fresh slice each generation), ``holdout`` decides (rotated
every ``holdout_rotate`` generations), and ``final`` is only for the end-of-run report.
"""

from __future__ import annotations

import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

SEED_RANGE = 2**31


def rng_for(run_seed: int, generation: int, purpose: str) -> np.random.Generator:
    """The random stream for one purpose in one generation: same inputs, same numbers."""
    return np.random.default_rng([run_seed, generation, zlib.crc32(purpose.encode())])


@dataclass(frozen=True)
class SeedPools:
    dev: tuple[int, ...]
    holdout: tuple[int, ...]
    final: tuple[int, ...]
    dev_pairs: int
    holdout_pairs: int
    holdout_rotate: int

    @staticmethod
    def generate(
        run_seed: int,
        dev_pool: int = 10_000,
        dev_pairs: int = 100,
        holdout_pairs: int = 100,
        holdout_blocks: int = 10,
        holdout_rotate: int = 10,
        final_pairs: int = 200,
    ) -> SeedPools:
        """Draw every pool at once without repeats, so they are disjoint by construction.

        Each holdout block holds ``2 * holdout_pairs`` seeds: the decision sample plus its
        one allowed extension.
        """
        if dev_pairs > dev_pool:
            raise ValueError("dev_pairs cannot exceed the dev pool")
        sizes = (dev_pool, 2 * holdout_pairs * holdout_blocks, final_pairs)
        rng = rng_for(run_seed, 0, "seed-pools")
        drawn: list[int] = []
        seen: set[int] = set()
        while len(drawn) < sum(sizes):
            for s in rng.integers(0, SEED_RANGE, size=sum(sizes)).tolist():
                if s not in seen and len(drawn) < sum(sizes):
                    seen.add(s)
                    drawn.append(int(s))
        a, b = sizes[0], sizes[0] + sizes[1]
        return SeedPools(
            tuple(drawn[:a]),
            tuple(drawn[a:b]),
            tuple(drawn[b:]),
            dev_pairs,
            holdout_pairs,
            holdout_rotate,
        )

    def dev_slice(self, run_seed: int, generation: int, index: int = 0) -> tuple[int, ...]:
        """A fresh dev sample for one candidate of one generation."""
        rng = rng_for(run_seed, generation, f"dev-slice-{index}")
        picks = rng.choice(len(self.dev), size=self.dev_pairs, replace=False)
        return tuple(self.dev[int(i)] for i in picks)

    def holdout_block(self, generation: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """(decision seeds, extension seeds) for a generation; the block rotates."""
        size = 2 * self.holdout_pairs
        blocks = len(self.holdout) // size
        block = ((generation - 1) // self.holdout_rotate) % blocks
        seeds = self.holdout[block * size : (block + 1) * size]
        return seeds[: self.holdout_pairs], seeds[self.holdout_pairs :]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dev_pairs": self.dev_pairs,
            "holdout_pairs": self.holdout_pairs,
            "holdout_rotate": self.holdout_rotate,
            "dev": list(self.dev),
            "holdout": list(self.holdout),
            "final": list(self.final),
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> SeedPools:
        return SeedPools(
            tuple(d["dev"]),
            tuple(d["holdout"]),
            tuple(d["final"]),
            d["dev_pairs"],
            d["holdout_pairs"],
            d["holdout_rotate"],
        )
