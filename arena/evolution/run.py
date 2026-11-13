"""Five lineages in lockstep (phase 4 spec, sections 1, 2 and 4).

```
runs/<id>/
  evolution.json                 profile, run seed, lineage order, and provenance: hashes
                                 of the framework and of the whole arena package (engine,
                                 policies, hand-set params, evaluator), Python and NumPy
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
import platform
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy

from arena.agents.params import ParamSet, save_params
from arena.agents.registry import PERSONALITIES
from arena.engine.rng import derive_seed
from arena.evolution import cup
from arena.evolution.entrants import Entrant, hand_set, param_specs, personality_class
from arena.evolution.evaluator import Context, EvalSettings, SnakeEvaluator, Workers
from arena.evolution.league import league_halls, with_league
from arena.rsi.accept import GuardMetric, PairedBootstrapRule
from arena.rsi.coach import HarnessCoach
from arena.rsi.harness import AdaptiveHarness
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
    patience: int | None = 4
    min_rel_gain: float = 0.02
    resamples: int = 10_000
    proposer: str = "gaussian_hill_climb"
    death_rate_tolerance: float = 0.15
    death_rate_slack: float = 0.05
    self_wall_tolerance: float = 0.25
    self_wall_slack: float = 0.05
    cup: cup.CupSettings | None = None

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
        settings = EvalSettings(
            s["width"],
            s["height"],
            s["ticks"],
            tuple(s["shares"].values()),
            s.get("length", 5),
            s.get("objective", "kills"),
        )
        cup_settings = cup.CupSettings(**d["cup"]) if d.get("cup") else None
        return Profile(**{**d, "settings": settings, "cup": cup_settings})


PROFILES: dict[str, Profile] = {
    "default": Profile("default", EvalSettings(150, 150, 5000)),
    "experiment": Profile(
        "experiment",
        EvalSettings(36, 36, 2000),
        dev_pairs=40,
        holdout_pairs=40,
        final_pairs=100,
    ),
    "arena": Profile(
        "arena",
        EvalSettings(30, 30, 2000, objective="score"),
        dev_pairs=20,
        holdout_pairs=30,
        final_pairs=60,
        patience=None,
        proposer="harness",
        cup=cup.CupSettings(),
    ),
    "quick": Profile(
        "quick", EvalSettings(60, 60, 1000), dev_pairs=20, holdout_pairs=20, final_pairs=40
    ),
}
"""``default`` is the specified experiment. ``experiment`` is a reduced, labelled setting
that fits a single machine and puts snakes close enough to meet: with 5-cell snakes on
40 x 40 boards and 1,000-tick episodes only 0-5 of 40 paired seeds scored any kill, and
the default profile costs hours per generation here (specs/plan.md, Measurements).
``quick`` is a fast end-to-end check whose results are never reported as the experiment.
These three were scaled by 1.5 when snakes grew from 5 to 10 cells; runs saved before
that load their old size.

``arena`` is the open-ended setting: lineages tune themselves on the viewer's 30 x 30
board for points (kills minus self-inflicted deaths), every lineage runs the
self-tuning ``harness`` proposer with its strategy prior, nothing stops on patience, and
after each generation the champions play the arena cup (``arena/evolution/cup.py``)."""

STRATEGY_PRIORS: dict[str, dict[str, float]] = {
    "hunter": {
        "w_cut_off": 2.0,
        "w_nearest_enemy_head": 2.0,
        "w_territory": 1.5,
        "search_radius": 1.5,
        "w_head_on_risk": 1.5,
    },
    "survivor": {
        "w_space": 2.0,
        "w_wall_distance": 2.0,
        "w_space_vs_length": 1.5,
        "w_head_on_risk": 1.5,
        "keep_distance": 1.5,
    },
    "trapper": {
        "w_enemy_space_after": 2.0,
        "w_enemy_escape_moves": 2.0,
        "w_cut_off": 1.5,
        "keep_distance": 1.5,
    },
    "predictor": {
        "w_expected_kills": 2.0,
        "w_expected_death": 2.0,
        "w_pressure": 1.5,
        "lookahead": 1.5,
        "discount": 1.5,
    },
    "opportunist": {
        "attack_threshold": 2.0,
        "attack_cut_off": 1.5,
        "attack_enemy_escape_moves": 1.5,
        "attack_enemy_space_after": 1.5,
        "cruise_space": 1.5,
    },
}
"""Where each lineage's harness starts looking: the parameters closest to the
personality's objective (phase 2 spec) get picked more often at first. The harness then
moves these weights by what its candidates did in play, and decays them back to here."""


def strategy_brief(name: str) -> str:
    """What a lineage is for, in words, for a harness coach: the personality's module
    docstring and its objective in the arena profile."""
    module = sys.modules[personality_class(name).__module__]
    doc = " ".join((module.__doc__ or name).split())
    return (
        f"Snake personality '{name}': {doc} It plays 2,000-tick games on a 30 x 30 board "
        "against four other snakes and is scored by points: kills minus deaths it causes "
        "itself (walls, its own body). Candidates that crash more are penalised."
    )


def lineage_proposer(
    profile: Profile, name: str, coach: Callable[[str], HarnessCoach] | None = None
) -> Proposer:
    """The proposer for one lineage; ``harness`` gets the lineage's strategy prior and
    learns to avoid candidates that crash into walls or themselves more. ``coach`` makes
    the lineage's harness coach for the opt-in model-steered harness."""
    if profile.proposer == "harness":
        return AdaptiveHarness(
            priors=STRATEGY_PRIORS.get(name, {}),
            penalties={"self_wall_deaths": 0.5, "deaths_per_1k_alive": 0.25},
            coach=coach(name) if coach is not None else None,
        )
    return make_proposer(profile.proposer)


def provenance() -> dict[str, str]:
    """What a run's numbers depend on besides its identity (vision section 8)."""
    package = Path(__file__).resolve().parent.parent
    return {
        "code_hash": code_hash(),
        "arena_hash": code_hash(package, ("*.py", "*.json")),
        "python": platform.python_version(),
        "numpy": numpy.__version__,
    }


def lineage_seed(run_seed: int, name: str) -> int:
    return derive_seed(run_seed, "lineage", name) % 2**31


@dataclass
class Lineage:
    name: str
    run: Run
    evaluator: SnakeEvaluator

    accepts: list[tuple[int, Candidate]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        """Read the accepted champions once; ``commit`` keeps the list current, so a
        long run never re-parses its whole ``generations.jsonl`` each generation."""
        by_id = {m.id: m for m in self.run.store.archive.members}
        self.accepts = [
            (rec["generation"], by_id[rec["champion_after"]])
            for rec in self.records()
            if rec["decision"]["accept"]
        ]

    def records(self) -> list[dict[str, Any]]:
        return self.run.store.records()

    def commit(self, pending: Pending) -> None:
        self.run.commit(pending)
        if pending.record["decision"]["accept"]:
            self.accepts.append((pending.generation, pending.champion))

    def hall(self, upto: int) -> list[Candidate]:
        """Every champion this lineage has had after generation ``upto``, oldest first."""
        return [self.run.baseline, *(c for g, c in self.accepts if g <= upto)]


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
        max_seconds: float | None = None,
        max_episodes: int | None = None,
        proposer: Callable[[str], Proposer] | None = None,
        rule: AcceptanceRule | None = None,
        log: Callable[[str], None] = lambda _: None,
        until_wins: int | None = None,
    ) -> None:
        self.dir = Path(run_dir)
        self.profile = profile
        self.generations = generations
        self.run_seed = run_seed
        self.workers = Workers(workers)
        self.names = lineages
        self.max_seconds = max_seconds
        self.max_episodes = max_episodes
        self.make_proposer = proposer or (lambda name: lineage_proposer(profile, name))
        self.rule = rule or profile.rule()
        self.log = log
        self.until_wins = until_wins
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
            write_json(meta, {"identity": self.identity(), **provenance()})
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
                budget=Budget(self.generations, self.max_episodes),
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
        """Every lineage frozen as it stood after generation ``upto``, plus any league
        exploiters that had joined by then (``arena/evolution/league.py``)."""
        ctx = make_context({name: lin.hall(upto) for name, lin in self.lineages.items()})
        return with_league(ctx, league_halls(self.dir, upto))

    def _set_context(self, upto: int) -> None:
        halls = {name: lin.hall(upto) for name, lin in self.lineages.items()}
        ctx = with_league(make_context(halls), league_halls(self.dir, upto))
        for name, lin in self.lineages.items():
            lin.evaluator.context = ctx
            lin.evaluator.version = {c.id: v for v, c in enumerate(halls[name], start=1)}

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

    def seconds(self) -> float:
        """Wall time of every finished generation, summed over resumes."""
        path = self.dir / "timing.jsonl"
        if not path.exists():
            return 0.0
        return sum(float(json.loads(line)["seconds"]) for line in path.read_text().splitlines())

    def cup_wins(self) -> dict[str, int]:
        return dict(cup.standings(cup.read_cup(self.dir)))

    def stop_reason(self) -> str | None:
        if (self.dir / "STOP").exists():
            return "stop file"
        if self.until_wins is not None and self.profile.cup is not None:
            wins = self.cup_wins()
            leader = max(wins, key=lambda n: (wins[n], n), default=None)
            if leader is not None and wins[leader] >= self.until_wins:
                return f"{leader} reached {wins[leader]} cup wins"
        if self.max_seconds is not None and self.seconds() >= self.max_seconds:
            return "time budget"
        if not self.active():
            reasons = {lin.run.stop_reason() for lin in self.lineages.values()}
            return str(reasons.pop()) if len(reasons) == 1 else "every lineage stopped"
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
                    lin.commit(p)
                    self._write_params(lin, lin.hall(g))
                self._play_cup(g)
                seconds = time.monotonic() - started
                self._log_generation(g, pending, seconds, episodes)
                self._dashboard()
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
            self._dashboard()
            return EvolutionResult(final_g, reason, results)
        finally:
            self.workers.close()

    def _play_cup(self, g: int) -> None:
        settings = self.profile.cup
        if settings is None or any(r["generation"] == g for r in cup.read_cup(self.dir)):
            return
        champions = {}
        for name, lin in self.lineages.items():
            hall = lin.hall(g)
            champions[name] = Entrant.personality(name, hall[-1].params, len(hall))
        tasks = cup.cup_tasks(settings, self.run_seed, g, champions)
        matches = self.workers.map(cup.play_cup_match, tasks)
        cup.append_cup(self.dir, g, matches)
        won = cup.standings([{"matches": matches}])
        self.log(
            f"cup generation {g}: {cup.format_standings(won, self.names)}; "
            f"total: {cup.format_standings(cup.standings(cup.read_cup(self.dir)), self.names)}"
        )

    def _dashboard(self) -> None:
        """Rewrite dashboard.html; a broken page must never stop a long run."""
        from arena.evolution import dashboard

        try:
            dashboard.write(self.dir)
        except Exception as exc:
            self.log(f"  dashboard not updated: {exc!r}")

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
        for lin, _ in pending:
            summary = getattr(lin.run.proposer, "summary", None)
            if callable(summary):
                parts.append(f"  {lin.name:<12}harness {json.dumps(summary())}")
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
