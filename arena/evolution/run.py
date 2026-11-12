"""Five lineages in lockstep (phase 4 spec, sections 1, 2 and 4).

```
runs/<id>/
  evolution.json                 profile, run seed, lineage order, code hash
  lineages/<name>/               one phase 3 run directory per personality
  params/<name>/v<k>.json        every champion as a version-stamped params file
  params/<name>.json             the latest champion
  timing.jsonl                   wall time per generation (machine-dependent, so kept
                                 apart from the deterministic records)
```

Generation ``g`` freezes every lineage's champion as it stood after generation ``g - 1``
(read back from the stored records, so a resumed run builds the same context), gives
each active lineage one phase 3 step against that frozen context in the fixed order,
then commits all of them. A lineage that runs out of patience stops proposing but its
champion keeps playing as an opponent.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from arena.agents.params import ParamSet, save_params
from arena.agents.registry import PERSONALITIES
from arena.engine.rng import derive_seed
from arena.evolution.entrants import Entrant, hand_set, param_specs, personality_class
from arena.evolution.evaluator import Context, EvalSettings, SnakeEvaluator, Workers
from arena.rsi.accept import GuardMetric, PairedBootstrapRule
from arena.rsi.loop import Pending, Run, RunConfig, RunResult
from arena.rsi.proposers import make_proposer
from arena.rsi.store import code_hash, read_json, write_json
from arena.rsi.types import AcceptanceRule, Budget, Candidate, Proposer


@dataclass(frozen=True)
class Profile:
    """Everything that defines an evolution experiment except its length and seed."""

    name: str
    settings: EvalSettings
    dev_pairs: int = 100
    holdout_pairs: int = 100
    holdout_blocks: int = 10
    holdout_rotate: int = 10
    final_pairs: int = 200
    dev_pool: int = 10_000
    patience: int = 4
    min_rel_gain: float = 0.02
    resamples: int = 10_000
    proposer: str = "gaussian_hill_climb"
    death_rate_tolerance: float = 0.15
    death_rate_slack: float = 0.05
    self_wall_tolerance: float = 0.25
    self_wall_slack: float = 0.05

    def rule(self) -> PairedBootstrapRule:
        return PairedBootstrapRule(
            self.min_rel_gain,
            self.resamples,
            guards=(
                GuardMetric(
                    "deaths_per_1k_alive", self.death_rate_tolerance, True, self.death_rate_slack
                ),
                GuardMetric(
                    "self_wall_deaths", self.self_wall_tolerance, True, self.self_wall_slack
                ),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["settings"] = self.settings.to_dict()
        return d

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> Profile:
        s = d["settings"]
        settings = EvalSettings(s["width"], s["height"], s["ticks"], tuple(s["shares"].values()))
        return Profile(**{**d, "settings": settings})


PROFILES: dict[str, Profile] = {
    "default": Profile("default", EvalSettings(100, 100, 5000)),
    "experiment": Profile(
        "experiment",
        EvalSettings(24, 24, 2000),
        dev_pairs=40,
        holdout_pairs=40,
        final_pairs=100,
    ),
    "quick": Profile(
        "quick", EvalSettings(40, 40, 1000), dev_pairs=20, holdout_pairs=20, final_pairs=40
    ),
}
"""``default`` is the specified experiment. ``experiment`` is a reduced, labelled setting
that fits a single machine and puts snakes close enough to meet: on 40 x 40 boards with
1,000-tick episodes only 0-5 of 40 paired seeds scored any kill, and the default profile
costs hours per generation here (specs/plan.md, Measurements). ``quick`` is a fast
end-to-end check whose results are never reported as the experiment."""


def lineage_seed(run_seed: int, name: str) -> int:
    return derive_seed(run_seed, "lineage", name) % 2**31


@dataclass
class Lineage:
    name: str
    run: Run
    evaluator: SnakeEvaluator

    def records(self) -> list[dict[str, Any]]:
        return self.run.store.records()

    def hall(self, upto: int) -> list[Candidate]:
        """Every champion this lineage has had after generation ``upto``, oldest first."""
        by_id = {m.id: m for m in self.run.store.archive.members}
        out = [self.run.baseline]
        for rec in self.records():
            if rec["generation"] > upto:
                break
            if rec["decision"]["accept"]:
                out.append(by_id[rec["champion_after"]])
        return out


@dataclass
class EvolutionResult:
    generations: int
    stop_reason: str
    lineages: dict[str, RunResult] = field(default_factory=dict)


def make_context(halls: Mapping[str, Sequence[Candidate]]) -> Context:
    """The opponent context for halls of fame given oldest first; a personality without
    a lineage plays as its hand-set self."""
    champions: list[Entrant] = []
    hall_entrants: list[tuple[Entrant, ...]] = []
    reference: list[Entrant] = []
    for name in PERSONALITIES:
        ref = Entrant.personality(name, hand_set(name), 1)
        hall = tuple(
            Entrant.personality(name, c.params, v)
            for v, c in enumerate(halls.get(name) or (), start=1)
        ) or (ref,)
        champions.append(hall[-1])
        hall_entrants.append(hall)
        reference.append(ref)
    return Context(tuple(champions), tuple(hall_entrants), tuple(reference))


class Evolution:
    """One phase 4 run in ``run_dir``; calling ``run()`` again resumes it."""

    def __init__(
        self,
        run_dir: str | Path,
        profile: Profile,
        generations: int,
        run_seed: int = 0,
        workers: int | None = None,
        lineages: tuple[str, ...] = PERSONALITIES,
        proposer: Callable[[str], Proposer] | None = None,
        rule: AcceptanceRule | None = None,
        log: Callable[[str], None] = lambda _: None,
    ) -> None:
        self.dir = Path(run_dir)
        self.profile = profile
        self.generations = generations
        self.run_seed = run_seed
        self.workers = Workers(workers)
        self.names = lineages
        self.make_proposer = proposer or (lambda _: make_proposer(profile.proposer))
        self.rule = rule or profile.rule()
        self.log = log
        self.lineages: dict[str, Lineage] = {}

    def identity(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "run_seed": self.run_seed,
            "lineages": list(self.names),
        }

    def _open(self) -> None:
        meta = self.dir / "evolution.json"
        if meta.exists():
            stored = read_json(meta)
            if stored["identity"] != self.identity():
                raise ValueError(
                    f"{self.dir} holds a different evolution run; only --generations may "
                    "change on resume"
                )
        else:
            self.dir.mkdir(parents=True, exist_ok=True)
            write_json(meta, {"identity": self.identity(), "code_hash": code_hash()})
        p = self.profile
        rule = self.rule
        for name in self.names:
            start = hand_set(name)
            config = RunConfig(
                run_seed=lineage_seed(self.run_seed, name),
                problem=f"snake:{name}",
                dev_pairs=p.dev_pairs,
                holdout_pairs=p.holdout_pairs,
                holdout_rotate=p.holdout_rotate,
                holdout_blocks=p.holdout_blocks,
                dev_pool=p.dev_pool,
                final_pairs=p.final_pairs,
                patience=p.patience,
                budget=Budget(generations=self.generations),
            )
            evaluator = SnakeEvaluator(name, p.settings, self.workers)
            run = Run(
                self.dir / "lineages" / name,
                param_specs(name, start),
                evaluator,
                self.make_proposer(name),
                rule,
                config,
                baseline=start,
            )
            run.open()
            self.lineages[name] = Lineage(name, run, evaluator)
        for lin in self.lineages.values():
            self._write_params(lin, lin.hall(lin.run.generation))

    def context(self, upto: int) -> Context:
        """Every lineage frozen as it stood after generation ``upto``."""
        return make_context({name: lin.hall(upto) for name, lin in self.lineages.items()})

    def _set_context(self, upto: int) -> None:
        ctx = self.context(upto)
        for lin in self.lineages.values():
            lin.evaluator.context = ctx
            hall = lin.hall(upto)
            lin.evaluator.version = {c.id: v for v, c in enumerate(hall, start=1)}

    def _write_params(self, lin: Lineage, hall: list[Candidate]) -> None:
        space = personality_class(lin.name).param_space
        folder = self.dir / "params" / lin.name
        for version, cand in enumerate(hall, start=1):
            path = folder / f"v{version}.json"
            if not path.exists():
                save_params(ParamSet(lin.name, version, cand.params), space, path)
        latest = ParamSet(lin.name, len(hall), hall[-1].params)
        save_params(latest, space, self.dir / "params" / f"{lin.name}.json")

    def active(self) -> list[Lineage]:
        return [lin for lin in self.lineages.values() if lin.run.stop_reason() is None]

    def stop_reason(self) -> str | None:
        if (self.dir / "STOP").exists():
            return "stop file"
        if not self.active():
            reasons = {lin.run.stop_reason() for lin in self.lineages.values()}
            return (
                "generation budget" if reasons == {"generation budget"} else "every lineage stopped"
            )
        return None

    def run(self) -> EvolutionResult:
        try:
            self._open()
            while (reason := self.stop_reason()) is None:
                active = self.active()
                g = min(lin.run.generation for lin in active) + 1
                started = time.monotonic()
                self._set_context(g - 1)
                pending: list[tuple[Lineage, Pending]] = []
                episodes = 0
                for lin in active:
                    if lin.run.generation < g:
                        before = lin.run.state["episodes"]
                        p = lin.run.step(g)
                        episodes += p.state["episodes"] - before
                        pending.append((lin, p))
                for lin, p in pending:
                    lin.run.commit(p)
                    self._write_params(lin, lin.hall(g))
                seconds = time.monotonic() - started
                self._log_generation(g, pending, seconds, episodes)
            final_g = max(lin.run.generation for lin in self.lineages.values())
            self._set_context(final_g)
            results = {}
            for name, lin in self.lineages.items():
                results[name] = lin.run.finish(lin.run.stop_reason() or reason)
            write_json(
                self.dir / "final.json",
                {
                    "generation": final_g,
                    "stop_reason": reason,
                    "lineages": {
                        name: {
                            "accepted": r.accepted,
                            "version": r.accepted + 1,
                            "stop_reason": r.stop_reason,
                            "final": r.final,
                        }
                        for name, r in results.items()
                    },
                },
            )
            return EvolutionResult(final_g, reason, results)
        finally:
            self.workers.close()

    def _log_generation(
        self, g: int, pending: list[tuple[Lineage, Pending]], seconds: float, episodes: int
    ) -> None:
        parts = [
            f"  {lin.name:<12}{'ACCEPT' if p.record['decision']['accept'] else 'reject'}  "
            f"{p.record['decision']['rationale']}"
            for lin, p in pending
        ]
        line = {
            "generation": g,
            "seconds": round(seconds, 3),
            "episodes": episodes,
            "workers": self.workers.count,
        }
        with open(self.dir / "timing.jsonl", "a") as f:
            f.write(json.dumps(line) + "\n")
        self.log("\n".join([f"generation {g} ({seconds:.0f} s)", *parts]))


def load_champion(run_dir: str | Path, name: str, version: int | None = None) -> Entrant:
    """A lineage's champion from a run directory: the latest, or version ``version``."""
    folder = Path(run_dir) / "params" / name
    if version is None:
        versions = sorted(int(p.stem[1:]) for p in folder.glob("v*.json"))
        if not versions:
            raise ValueError(f"no champions of {name} in {run_dir}")
        version = versions[-1]
    path = folder / f"v{version}.json"
    if not path.exists():
        raise ValueError(f"{name} has no version {version} in {run_dir}")
    data: Mapping[str, Any] = json.loads(path.read_text())
    return Entrant.personality(name, data["params"], int(data["version"]))
