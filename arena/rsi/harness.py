"""A search harness that tunes itself from what its own candidates did in play.

``AdaptiveHarness`` is a proposer made of proposers. Every generation it fills a batch of
candidates, choosing an operator for each (hill climb, coordinate search, cross-entropy,
archive crossover, random restart, (1+1)-CMA-ES) with a discounted UCB bandit whose
rewards come from the paired dev games those candidates played. On top of that it learns:

* **which parameters matter** for this lineage: parameters touched by candidates that beat
  the champion on dev get a larger weight, so later hill-climb steps pick them more often;
  a strategy prior (``priors``) sets where those weights start and what they decay to;
* **what to avoid while playing**: a candidate whose guard metrics got worse than the
  champion's (for snakes, crashing into walls or itself) earns a reward penalty;
* **how hard to search**: the batch grows by one after a generation in which no
  candidate beat the champion on dev and shrinks after an accept.

With a ``coach`` (``arena/rsi/coach.py``, opt-in) a language model reads that learned
state every few generations and rewrites the harness's own settings: operator biases,
the parameter priors it decays back to, its exploration constant and its largest batch.
Each patch is clipped, logged in the journal and kept in the saved state.

It only ever sees ``Feedback``: dev results and accept flags, never holdout seeds or
numbers, and it changes nothing but what is proposed and how many candidates are tried.
The acceptance rule and the evaluator stay fixed (phase 3 spec, section 4).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import numpy as np

from arena.rsi.coach import HarnessCoach
from arena.rsi.proposers import make_proposer
from arena.rsi.types import Candidate, Feedback, History, ParamSpec, Proposer

OPERATORS = (
    "gaussian_hill_climb",
    "coordinate_search",
    "cross_entropy",
    "archive_crossover",
    "random_restart",
    "cma_es",
)


class AdaptiveHarness:
    name = "harness"

    def __init__(
        self,
        operators: Sequence[str] = OPERATORS,
        batch: int = 3,
        min_batch: int = 2,
        max_batch: int = 6,
        priors: Mapping[str, float] | None = None,
        penalties: Mapping[str, float] | None = None,
        explore: float = 1.0,
        decay: float = 0.9,
        journal: int = 40,
        coach: HarnessCoach | None = None,
    ) -> None:
        if not operators:
            raise ValueError("the harness needs at least one operator")
        self.ops: dict[str, Proposer] = {n: make_proposer(n) for n in operators}
        self.batch = batch
        self.min_batch, self.max_batch = min_batch, max_batch
        self.ceiling = max_batch
        self.priors = {k: float(v) for k, v in (priors or {}).items()}
        self.penalties = {k: float(v) for k, v in (penalties or {}).items()}
        self.explore = explore
        self.decay = decay
        self.journal_size = journal
        self.stats: dict[str, dict[str, float]] = {n: {"n": 0.0, "reward": 0.0} for n in self.ops}
        self.weights: dict[str, float] = dict(self.priors)
        self.journal: list[dict[str, Any]] = []
        self._origin: dict[str, tuple[str, tuple[str, ...]]] = {}
        self._used: dict[str, int] = {}
        self.coach = coach
        self.bias: dict[str, float] = {}
        self._view: dict[str, Any] = {}

    # -- choosing ------------------------------------------------------------------

    def _score(self, op: str, total: float) -> float:
        s = self.stats[op]
        if s["n"] < 1e-9:
            return math.inf
        mean = s["reward"] / s["n"]
        bonus = self.explore * math.sqrt(math.log(total + 1.0) / s["n"])
        return mean + bonus + self.bias.get(op, 0.0) - 0.25 * self._used.get(op, 0)

    def choose(self, rng: np.random.Generator) -> str:
        total = sum(s["n"] for s in self.stats.values())
        scores = {op: self._score(op, total) for op in self.ops}
        best = max(scores.values())
        ties = sorted(op for op, v in scores.items() if v == best)
        return ties[int(rng.integers(len(ties)))]

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        if not self._origin:
            self._used = {}
            self._view = {
                "parameters": [
                    {
                        "name": p.name,
                        "low": p.low,
                        "high": p.high,
                        "champion": round(champion.params.get(p.name, 0.0), 4),
                    }
                    for p in space
                ]
            }
        op = self.choose(rng)
        self._used[op] = self._used.get(op, 0) + 1
        inner = self.ops[op]
        if hasattr(inner, "weights"):
            inner.weights = {p.name: self.weights.get(p.name, 1.0) for p in space}
        cand = inner.propose(champion, history, space, rng)
        touched = tuple(
            sorted(
                p.name
                for p in space
                if abs(cand.params.get(p.name, 0.0) - champion.params.get(p.name, 0.0)) > 1e-12
            )
        )
        self._origin[cand.id] = (op, touched)
        return replace(cand, proposer=f"{self.name}/{op}", note=f"[{op}] {cand.note}")

    # -- learning ------------------------------------------------------------------

    def reward(self, f: Feedback) -> float:
        """0..2: how promising the candidate looked on dev, +1 if it was accepted."""
        if f.dev is None or f.stage == "validate":
            return 0.0
        diffs = f.dev.diffs
        sd = float(np.std(diffs, ddof=1)) if len(diffs) > 1 else 0.0
        se = sd / math.sqrt(len(diffs)) if sd > 0 else 1.0
        t = float(np.mean(diffs)) / se if len(diffs) else 0.0
        r = min(1.0, max(0.0, 0.5 + t / 6.0))
        guards = f.dev.diagnostics.get("guards", {}) if f.dev.diagnostics else {}
        for name, weight in self.penalties.items():
            if name in guards:
                a, b = guards[name]
                if a > b * 1.1 + 1e-9:
                    r -= weight * min(1.0, (a - b) / (abs(b) + 1e-9))
        return max(0.0, r) + (1.0 if f.accepted else 0.0)

    def observe(self, feedback: Sequence[Feedback]) -> None:
        mine = [f for f in feedback if f.candidate.id in self._origin]
        if not mine:
            self._origin.clear()
            return
        for s in self.stats.values():
            s["n"] *= self.decay
            s["reward"] *= self.decay
        for name in list(self.weights):
            prior = self.priors.get(name, 1.0)
            self.weights[name] = prior + 0.95 * (self.weights[name] - prior)
        by_op: dict[str, list[Feedback]] = {}
        entry: dict[str, Any] = {"generation": mine[0].generation, "batch": self.batch}
        rewards: list[list[Any]] = []
        tried: list[dict[str, Any]] = []
        beat = accepted = False
        for f in mine:
            op, touched = self._origin[f.candidate.id]
            r = self.reward(f)
            rewards.append([op, round(r, 3)])
            tried.append(
                {
                    "op": op,
                    "touched": list(touched[:6]),
                    "dev_diff": round(f.dev.mean_diff, 3) if f.dev is not None else None,
                    "accepted": f.accepted,
                }
            )
            self.stats[op]["n"] += 1.0
            self.stats[op]["reward"] += r
            by_op.setdefault(op, []).append(f)
            for name in touched:
                w = self.weights.get(name, self.priors.get(name, 1.0))
                self.weights[name] = min(4.0, max(0.25, w * math.exp(0.4 * (min(r, 1.0) - 0.5))))
            beat |= f.dev is not None and f.dev.mean_diff > 0
            accepted |= f.accepted
        for op, fs in by_op.items():
            self.ops[op].observe(fs)
        if accepted:
            self.batch = max(self.min_batch, self.batch - 1)
        elif not beat:
            self.batch = min(self.max_batch, self.batch + 1)
        entry["rewards"] = rewards
        entry["candidates"] = tried
        entry["next_batch"] = self.batch
        generation = int(mine[0].generation)
        if self.coach is not None and self.coach.due(generation):
            patch = self.coach.advise(
                generation, self.coach_view(entry), list(self.ops), self._param_names()
            )
            if patch:
                self.apply_patch(patch)
                entry["coach"] = patch
        self.journal = [*self.journal, entry][-self.journal_size :]
        self._origin.clear()

    # -- coaching ------------------------------------------------------------------

    def _param_names(self) -> list[str]:
        return [p["name"] for p in self._view.get("parameters", [])]

    def coach_view(self, latest: Mapping[str, Any]) -> dict[str, Any]:
        """What the coach reads: the harness's learned state and recent dev outcomes."""
        params = [
            p
            | {
                "weight": round(self.weights.get(p["name"], 1.0), 3),
                "prior": self.priors.get(p["name"], 1.0),
            }
            for p in self._view.get("parameters", [])
        ]
        operators = {
            op: {
                "uses": round(s["n"], 2),
                "mean_reward": round(s["reward"] / s["n"], 3) if s["n"] > 1e-9 else None,
                "bias": self.bias.get(op, 0.0),
            }
            for op, s in self.stats.items()
        }
        recent = [*self.journal[-5:], latest]
        return {
            "reward_scale": "0..1 from the dev t-statistic (0.5 = even), +1 if accepted",
            "harness": {
                "batch": self.batch,
                "max_batch": self.max_batch,
                "explore": self.explore,
            },
            "operators": operators,
            "parameters": params,
            "recent_generations": [
                {k: e[k] for k in ("generation", "rewards", "candidates", "coach") if k in e}
                for e in recent
            ],
        }

    def apply_patch(self, patch: Mapping[str, Any]) -> None:
        """Apply a clipped coach patch (``arena/rsi/coach.py``) to the harness settings."""
        for op, b in patch.get("operator_bias", {}).items():
            if op in self.ops:
                self.bias[op] = float(b)
        for name, w in patch.get("param_priors", {}).items():
            self.priors[name] = float(w)
            current = self.weights.get(name, 1.0)
            self.weights[name] = min(4.0, max(0.25, 0.5 * (current + float(w))))
        if "explore" in patch:
            self.explore = float(patch["explore"])
        if "max_batch" in patch:
            self.max_batch = min(self.ceiling, max(self.min_batch, int(patch["max_batch"])))
            self.batch = min(self.batch, self.max_batch)

    # -- persistence ---------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        return {
            "batch": self.batch,
            "stats": {k: dict(v) for k, v in self.stats.items()},
            "weights": dict(sorted(self.weights.items())),
            "ops": {k: op.state() for k, op in self.ops.items()},
            "journal": list(self.journal),
            "bias": dict(sorted(self.bias.items())),
            "priors": dict(sorted(self.priors.items())),
            "explore": self.explore,
            "max_batch": self.max_batch,
            "coach": self.coach.state() if self.coach is not None else None,
        }

    def load_state(self, state: Mapping[str, Any]) -> None:
        self.batch = int(state["batch"])
        for k, v in state["stats"].items():
            if k in self.stats:
                self.stats[k] = {"n": float(v["n"]), "reward": float(v["reward"])}
        self.weights = {k: float(v) for k, v in state["weights"].items()}
        for k, s in state["ops"].items():
            if k in self.ops:
                self.ops[k].load_state(s)
        self.journal = list(state.get("journal", []))
        self.bias = {k: float(v) for k, v in state.get("bias", {}).items() if k in self.ops}
        if "priors" in state:
            self.priors = {k: float(v) for k, v in state["priors"].items()}
        self.explore = float(state.get("explore", self.explore))
        self.max_batch = min(self.ceiling, int(state.get("max_batch", self.max_batch)))
        self.batch = min(self.batch, self.max_batch)
        if self.coach is not None and state.get("coach"):
            self.coach.load_state(state["coach"])

    def summary(self) -> dict[str, Any]:
        """What the harness has learned, for logs and reports."""
        means = {
            op: round(s["reward"] / s["n"], 3) if s["n"] > 1e-9 else None
            for op, s in self.stats.items()
        }
        top = sorted(self.weights.items(), key=lambda kv: -kv[1])[:5]
        out: dict[str, Any] = {
            "batch": self.batch,
            "operator_reward": means,
            "top_params": dict(top),
        }
        if self.bias or self.coach is not None:
            out["coached"] = {
                "bias": {k: round(v, 2) for k, v in sorted(self.bias.items()) if v},
                "explore": round(self.explore, 2),
                "max_batch": self.max_batch,
            }
        return out
