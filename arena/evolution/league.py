"""The league file: exploiter snakes that join an evolve run's halls of fame (step 5.4).

``<run>/league.json`` lists exploiters (``arena/evolution/exploit.py``) with the
generation after which they join. ``Evolution.context(upto)`` appends every entry with
``joins_after <= upto`` to its personality's hall, so the "hall of fame" share of the
other lineages' games may seat it. Champions and versions never change, and an entry
joins only after the generation that was current when it was registered, so committed
generations stay reproducible on resume. A run without the file behaves as before.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from arena.agents.registry import PERSONALITIES
from arena.evolution.entrants import Entrant
from arena.evolution.evaluator import Context
from arena.rsi.store import read_json, write_atomic

LEAGUE = "league.json"


def league_entries(run_dir: str | Path) -> list[dict[str, Any]]:
    path = Path(run_dir) / LEAGUE
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = read_json(path)["exploiters"]
    return entries


def register(run_dir: str | Path, entry: Mapping[str, Any]) -> None:
    """Add (or replace, by name and target generation) one league entry atomically."""
    key = (entry["name"], entry["target_generation"])
    entries = [e for e in league_entries(run_dir) if (e["name"], e["target_generation"]) != key]
    entries.append(dict(entry))
    entries.sort(key=lambda e: (e["joins_after"], e["name"], e["target_generation"]))
    write_atomic(Path(run_dir) / LEAGUE, json.dumps({"exploiters": entries}, indent=2) + "\n")


def league_halls(run_dir: str | Path, upto: int) -> dict[str, tuple[Entrant, ...]]:
    """Exploiters that have joined by generation ``upto``, per personality, oldest first."""
    out: dict[str, list[Entrant]] = {}
    for e in league_entries(run_dir):
        if e["joins_after"] <= upto:
            label = f"{e['name']} exploiter g{e['target_generation']}"
            out.setdefault(e["name"], []).append(
                Entrant.personality(e["name"], e["params"], 0, label)
            )
    return {k: tuple(v) for k, v in out.items()}


def with_league(context: Context, extra: Mapping[str, Sequence[Entrant]]) -> Context:
    """``context`` with exploiters appended to the halls; champions stay as they are."""
    if not extra:
        return context
    halls = tuple(
        hall + tuple(extra.get(name, ()))
        for name, hall in zip(PERSONALITIES, context.halls, strict=True)
    )
    return Context(context.champions, halls, context.reference)
