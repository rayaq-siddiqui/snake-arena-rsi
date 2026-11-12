"""Archived champions as viewer policies (phase 4 spec, section 6).

Each lineage version becomes a named policy such as ``hunter@v4`` labelled "Hunter v4".
The lineups are the five champions after a generation, and with ``vs_generation`` one
six-seat lineup per lineage in which its evolved and earlier versions meet the other
four evolved champions.
"""

from __future__ import annotations

from pathlib import Path

from arena.agents.registry import STYLES
from arena.evolution.entrants import Entrant
from arena.evolution.report import LineageView, load_run
from arena.viz.server import Roster


def policy_name(lineage: str, version: int) -> str:
    return f"{lineage}@v{version}"


def latest_generation(views: dict[str, LineageView]) -> int:
    return max((len(v.records) for v in views.values()), default=0)


def run_roster(
    run_dir: str | Path, generation: int | None = None, vs_generation: int | None = None
) -> tuple[Roster, str]:
    """The run's champions as a viewer roster, and the lineup to open first."""
    _, views = load_run(Path(run_dir))
    last = latest_generation(views)
    gen = last if generation is None else generation
    for g in (gen, vs_generation):
        if g is not None and not 0 <= g <= last:
            raise ValueError(f"generation {g} is not in {run_dir} (0..{last})")
    roster = Roster()
    for name, view in views.items():
        for version, (_, champ) in enumerate(view.hall, start=1):
            entrant = Entrant.personality(name, champ.params, version)
            key = policy_name(name, version)
            roster.policies[key] = entrant.build
            roster.labels[key] = (entrant.label, STYLES[name][1])

    def at(g: int) -> dict[str, str]:
        return {n: policy_name(n, v.champion_at(g)[0]) for n, v in views.items()}

    now = at(gen)
    first = f"generation {gen}"
    roster.lineups[first] = list(now.values())
    if vs_generation is not None and vs_generation != gen:
        roster.lineups[f"generation {vs_generation}"] = list(at(vs_generation).values())
        then = at(vs_generation)
        for name in views:
            others = [p for n, p in now.items() if n != name]
            label = f"{STYLES[name][0]} gen {gen} vs gen {vs_generation}"
            roster.lineups[label] = [now[name], then[name], *others]
        changed = [n for n in views if now[n] != then[n]]
        first = f"{STYLES[(changed or list(views))[0]][0]} gen {gen} vs gen {vs_generation}"
    return roster, first
