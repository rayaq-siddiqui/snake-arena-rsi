"""The arena cup: the current champions play real matches, and wins are counted.

After every generation the five lineages' champions and one ``random_safe`` snake play
``matches`` full matches with the game's own win rule (first to ``target`` points, kills
minus self-inflicted deaths). Seats are shuffled per match. Wins add up over the whole
run in ``cup.jsonl``; ``Evolution`` can stop once a snake reaches ``until_wins``.

The cup only measures. No acceptance decision reads it, and its seeds come from their
own derivation, so they never overlap the dev, holdout or final pools by construction
of purpose (``derive_seed`` over distinct parts).
"""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arena.engine import GameConfig
from arena.engine.rng import derive_seed
from arena.evolution.entrants import Entrant
from arena.sim.match import Match

RANDOM = "random"


@dataclass(frozen=True)
class CupSettings:
    width: int = 30
    height: int = 30
    length: int = 10
    target: int = 10
    max_ticks: int = 20_000
    matches: int = 24

    def config(self, snakes: int = 6) -> GameConfig:
        return GameConfig(
            width=self.width,
            height=self.height,
            num_snakes=snakes,
            snake_length=self.length,
            score_target=self.target,
            max_ticks=self.max_ticks,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CupTask:
    config: GameConfig
    seed: int
    names: tuple[str, ...]
    entrants: tuple[Entrant, ...]


def cup_tasks(
    settings: CupSettings, run_seed: int, generation: int, champions: dict[str, Entrant]
) -> list[CupTask]:
    field = [*champions.items(), (RANDOM, Entrant("random_safe", label="Random"))]
    out = []
    for i in range(settings.matches):
        seed = derive_seed(run_seed, "cup", generation, i) % 2**63
        order = list(field)
        random.Random(seed).shuffle(order)
        out.append(
            CupTask(
                settings.config(len(field)),
                seed,
                tuple(n for n, _ in order),
                tuple(e for _, e in order),
            )
        )
    return out


def play_cup_match(task: CupTask) -> dict[str, Any]:
    result = Match([e.build() for e in task.entrants], task.seed, task.config).run()
    seat = {sid: task.names[i] for i, sid in enumerate(task.config.snake_ids)}
    return {
        "seed": task.seed,
        "ticks": result.ticks,
        "end": result.end_reason,
        "winner": seat[result.winner] if result.winner else None,
        "scores": {seat[s.snake]: s.score for s in result.standings},
        "versions": {n: e.version for n, e in zip(task.names, task.entrants, strict=True)},
    }


def read_cup(run_dir: Path) -> list[dict[str, Any]]:
    path = Path(run_dir) / "cup.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_cup(run_dir: Path, generation: int, matches: Sequence[dict[str, Any]]) -> None:
    with open(Path(run_dir) / "cup.jsonl", "a") as f:
        f.write(json.dumps({"generation": generation, "matches": list(matches)}) + "\n")


def standings(records: Sequence[dict[str, Any]]) -> Counter[str]:
    wins: Counter[str] = Counter()
    for rec in records:
        for m in rec["matches"]:
            if m["winner"] is not None:
                wins[m["winner"]] += 1
    return wins


def format_standings(wins: Counter[str], names: Sequence[str]) -> str:
    order = sorted([*names, RANDOM], key=lambda n: (-wins[n], n))
    return ", ".join(f"{n} {wins[n]}" for n in order)
