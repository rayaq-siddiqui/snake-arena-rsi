"""MAP-Elites: keep the best solution in each cell of a behaviour grid (plan step 5.2).

Mouret & Clune (2015). Instead of one champion, the archive is a grid over behaviour
descriptors (for the snakes: how close they stay to enemies, how much room they keep),
and each cell holds the fittest parameter set whose behaviour landed there. The search
is the classic one:

- the first ``init_batches`` batches are uniform random points (plus the start point);
- afterwards each candidate copies a random elite and adds N(0, sigma) to every
  parameter in normalised space, mapped back through ``ParamSpec.from_unit`` so it is
  valid by construction;
- a candidate takes its cell if the cell is empty or it beats the elite there.

Selection noise is the trap for any archive kept on noisy scores: every candidate is
scored on the same fixed dev seeds, so a lucky elite can sit in its cell. The run
therefore draws a disjoint holdout set from ``SeedPools`` that the search never sees and
re-scores every elite and the baseline on it at the end, paired by seed. Only those
holdout numbers are reported as results.

Each batch is drawn from ``rng_for(run_seed, batch, "map-elites")`` and the archive is
written atomically after each batch, so a stopped run resumes with the same numbers.
This module stays generic: the evaluator is any object with ``evaluate``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from arena.rsi.proposers import from_unit, to_unit
from arena.rsi.seeds import SeedPools, rng_for
from arena.rsi.store import read_json, write_json
from arena.rsi.types import ParamSpec

VERSION = 1


@dataclass(frozen=True)
class Axis:
    """One behaviour descriptor: its name, the range the grid covers and its bin count.
    Values outside the range land in the edge bins."""

    name: str
    low: float
    high: float
    bins: int

    def bin(self, value: float) -> int:
        frac = (value - self.low) / (self.high - self.low)
        return min(self.bins - 1, max(0, int(frac * self.bins)))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "low": self.low, "high": self.high, "bins": self.bins}


@dataclass(frozen=True)
class Evaluation:
    """Per-seed scores (higher is better) and the behaviour descriptors over those seeds."""

    scores: tuple[float, ...]
    descriptors: tuple[float, ...]

    @property
    def fitness(self) -> float:
        return float(np.mean(self.scores))


class BehaviourEvaluator(Protocol):
    def evaluate(
        self, params: Sequence[Mapping[str, float]], seeds: Sequence[int]
    ) -> list[Evaluation]: ...


@dataclass(frozen=True)
class MapElitesConfig:
    run_seed: int = 0
    batch: int = 16
    init_batches: int = 2
    sigma: float = 0.15
    dev_pairs: int = 20
    holdout_pairs: int = 40

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_seed": self.run_seed,
            "batch": self.batch,
            "init_batches": self.init_batches,
            "sigma": self.sigma,
            "dev_pairs": self.dev_pairs,
            "holdout_pairs": self.holdout_pairs,
        }


def _key(cell: Sequence[int]) -> str:
    return ",".join(map(str, cell))


class MapElites:
    """A MAP-Elites run in ``out``; calling ``run`` again resumes it."""

    def __init__(
        self,
        out: str | Path,
        space: Sequence[ParamSpec],
        axes: Sequence[Axis],
        evaluator: BehaviourEvaluator,
        config: MapElitesConfig,
        start: Mapping[str, float] | None = None,
        problem: str = "",
    ) -> None:
        self.out = Path(out)
        self.space = tuple(space)
        self.axes = tuple(axes)
        self.evaluator = evaluator
        self.config = config
        self.start = dict(start) if start is not None else {p.name: p.default for p in space}
        pools = SeedPools.generate(
            config.run_seed,
            dev_pool=config.dev_pairs,
            dev_pairs=config.dev_pairs,
            holdout_pairs=config.holdout_pairs,
            holdout_blocks=1,
            final_pairs=0,
        )
        self.dev_seeds = pools.dev
        self.holdout_seeds = pools.holdout[: config.holdout_pairs]
        self.identity = {
            "version": VERSION,
            "problem": problem,
            "config": config.to_dict(),
            "space": [p.name for p in self.space],
            "axes": [a.to_dict() for a in self.axes],
            "start": self.start,
        }
        self.cells: dict[str, dict[str, Any]] = {}
        self.batches = 0
        self.evaluations = 0
        self.history: list[dict[str, Any]] = []
        self._load()

    @property
    def path(self) -> Path:
        return self.out / "map_elites.json"

    def _load(self) -> None:
        if not self.path.exists():
            return
        state = read_json(self.path)
        if state["identity"] != self.identity:
            raise ValueError(f"{self.out} holds a different MAP-Elites run; use a new --out")
        self.cells = state["cells"]
        self.batches = state["batches"]
        self.evaluations = state["evaluations"]
        self.history = state["history"]

    def _save(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        state = {
            "identity": self.identity,
            "seeds": {"dev": list(self.dev_seeds)},
            "batches": self.batches,
            "evaluations": self.evaluations,
            "cells": dict(sorted(self.cells.items())),
            "history": self.history,
        }
        write_json(self.path, state)

    def cell_of(self, descriptors: Sequence[float]) -> tuple[int, ...]:
        return tuple(a.bin(v) for a, v in zip(self.axes, descriptors, strict=True))

    def _candidates(self, rng: np.random.Generator) -> list[dict[str, float]]:
        n = self.config.batch
        if self.batches < self.config.init_batches or not self.cells:
            out = [from_unit(rng.random(len(self.space)), self.space) for _ in range(n)]
            if self.batches == 0:
                out[0] = {p.name: p.from_unit(p.to_unit(self.start[p.name])) for p in self.space}
            return out
        keys = sorted(self.cells)
        out = []
        for _ in range(n):
            parent = self.cells[keys[int(rng.integers(len(keys)))]]["params"]
            u = to_unit(parent, self.space) + rng.normal(0.0, self.config.sigma, len(self.space))
            out.append(from_unit(u, self.space))
        return out

    def step(self) -> int:
        """Run one batch; returns how many cells it filled or improved."""
        rng = rng_for(self.config.run_seed, self.batches, "map-elites")
        params = self._candidates(rng)
        results = self.evaluator.evaluate(params, self.dev_seeds)
        changed = 0
        for p, ev in zip(params, results, strict=True):
            key = _key(self.cell_of(ev.descriptors))
            old = self.cells.get(key)
            if old is None or ev.fitness > old["fitness"]:
                self.cells[key] = {
                    "params": p,
                    "fitness": ev.fitness,
                    "descriptors": list(ev.descriptors),
                    "batch": self.batches,
                }
                changed += 1
        self.evaluations += len(params) * len(self.dev_seeds)
        self.batches += 1
        fits = [c["fitness"] for c in self.cells.values()]
        self.history.append(
            {
                "batch": self.batches,
                "changed": changed,
                "cells": len(self.cells),
                "best": max(fits),
                "qd_score": float(sum(fits)),
                "episodes": self.evaluations,
            }
        )
        self._save()
        return changed

    def run(self, batches: int, stop_file: Path | None = None) -> None:
        stop = stop_file or self.out / "STOP"
        while self.batches < batches and not stop.exists():
            self.step()

    def holdout(self, baseline: Mapping[str, float], resamples: int = 10_000) -> dict[str, Any]:
        """Re-score every elite and ``baseline`` on the holdout seeds, paired by seed, and
        write ``holdout.json``. The search never reads that file or those seeds."""
        keys = sorted(self.cells)
        params = [dict(baseline)] + [self.cells[k]["params"] for k in keys]
        results = self.evaluator.evaluate(params, self.holdout_seeds)
        base = np.array(results[0].scores)
        rng = rng_for(self.config.run_seed, 0, "map-elites-holdout")
        idx = rng.integers(0, len(base), size=(resamples, len(base)))
        elites = []
        for key, ev in zip(keys, results[1:], strict=True):
            diff = np.array(ev.scores) - base
            boot = diff[idx].mean(axis=1)
            lo, hi = np.percentile(boot, [2.5, 97.5])
            elites.append(
                {
                    "cell": key,
                    "params": self.cells[key]["params"],
                    "dev_fitness": self.cells[key]["fitness"],
                    "holdout_fitness": ev.fitness,
                    "holdout_cell": _key(self.cell_of(ev.descriptors)),
                    "holdout_descriptors": list(ev.descriptors),
                    "diff_vs_baseline": float(diff.mean()),
                    "ci": [float(lo), float(hi)],
                }
            )
        report = {
            "batches": self.batches,
            "n": len(base),
            "baseline": {
                "params": dict(baseline),
                "fitness": results[0].fitness,
                "descriptors": list(results[0].descriptors),
                "cell": _key(self.cell_of(results[0].descriptors)),
            },
            "elites": elites,
        }
        write_json(self.out / "holdout.json", report)
        return report
