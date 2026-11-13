"""MAP-Elites for one snake personality over the behaviour grid (plan step 5.2).

The grid is the phase 2 behaviour metrics: aggression as the mean Manhattan distance from
the snake's head to the nearest enemy head (low = aggressive), caution as the mean number
of cells reachable within ``SPACE_RADIUS`` steps (high = cautious). Both are measured the
same way for every policy (``arena/sim/metrics.py``).

Fitness is the lineage objective, kills per 1,000 ticks. Every parameter set plays the
same dev seeds against the hand-set reference portfolio, in the seat the seed picks, so
scores are comparable across cells. At the end every elite and the hand-set snake are
re-scored on holdout seeds the search never saw (``arena/rsi/map_elites.py``). The
result answers questions like "can a cautious Hunter kill as well as an aggressive one?"
with measured numbers instead of guesses.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.agents.registry import PERSONALITIES
from arena.evolution.entrants import Entrant, hand_set, param_specs
from arena.evolution.evaluator import EvalSettings, Workers, lineup
from arena.evolution.run import make_context
from arena.rsi.map_elites import Axis, Evaluation, MapElites, MapElitesConfig
from arena.sim.match import Match
from arena.sim.metrics import Behaviour

METRICS_EVERY = 10


@dataclass(frozen=True)
class GameTask:
    settings: EvalSettings
    seed: int
    seat: int
    entrants: tuple[Entrant, ...]


def play_one(task: GameTask) -> tuple[float, dict[str, int]]:
    """Kills per 1,000 ticks and the behaviour sums of the snake in ``task.seat``."""
    config = task.settings.config()
    match = Match(
        [e.build() for e in task.entrants], task.seed, config, metrics_every=METRICS_EVERY
    )
    result = match.run()
    sid = config.snake_ids[task.seat]
    kills = next(s.kills for s in result.standings if s.snake == sid)
    return kills * 1000 / task.settings.ticks, result.behaviour[sid].to_dict()


def default_axes(settings: EvalSettings) -> tuple[Axis, Axis]:
    """Aggression from 0 to a quarter of the board's Manhattan span (a snake whose nearest
    enemy head is farther than that on average is as unaggressive as the grid shows);
    caution from 30 to 80 of the at most 85 cells reachable within 6 steps, the range the
    hand-set personalities span (phase 4 report: 69-77 on the default board)."""
    return (
        Axis("enemy_distance", 0.0, (settings.width + settings.height) / 4, 8),
        Axis("space", 30.0, 80.0, 8),
    )


@dataclass
class SnakeBehaviourEvaluator:
    """Scores parameter sets of one personality against the hand-set reference snakes."""

    name: str
    settings: EvalSettings
    workers: Workers

    def evaluate(
        self, params: Sequence[Mapping[str, float]], seeds: Sequence[int]
    ) -> list[Evaluation]:
        me = PERSONALITIES.index(self.name)
        context = make_context({})
        tasks = []
        for p in params:
            entrant = Entrant.personality(self.name, p, 0)
            for seed in seeds:
                seat, _, opponents = lineup(context, me, seed, (0.0, 0.0, 1.0, 0.0))
                opponents.insert(seat, entrant)
                tasks.append(GameTask(self.settings, seed, seat, tuple(opponents)))
        played = self.workers.map(play_one, tasks)
        out = []
        n = len(seeds)
        for i in range(len(params)):
            chunk = played[i * n : (i + 1) * n]
            total = Behaviour()
            for _, sums in chunk:
                total.add(Behaviour(**sums))
            out.append(
                Evaluation(
                    tuple(score for score, _ in chunk),
                    (total.mean_enemy_distance or 0.0, total.mean_space or 0.0),
                )
            )
        return out


def snake_map_elites(
    name: str,
    out: str | Path,
    settings: EvalSettings,
    workers: Workers,
    config: MapElitesConfig,
) -> MapElites:
    """A resumable MAP-Elites run for personality ``name``, started from its hand-set
    parameters (which seed the first batch)."""
    start = hand_set(name)
    return MapElites(
        out,
        param_specs(name, start),
        default_axes(settings),
        SnakeBehaviourEvaluator(name, settings, workers),
        config,
        start=start,
        problem=f"{name} on {settings.width}x{settings.height}, {settings.ticks} ticks, "
        "vs the hand-set reference snakes",
    )


def heatmap_svg(state: Mapping[str, Any], holdout: Mapping[str, Any] | None = None) -> str:
    """The archive as an SVG grid: one square per cell, darker = more kills per 1k ticks.

    With a holdout report, cells show the holdout score and the hand-set snake's cell is
    outlined, so the picture shows measured numbers, not the dev scores the search used.
    """
    ax, ay = state["identity"]["axes"]
    nx, ny = ax["bins"], ay["bins"]
    size, left, top = 44, 70, 48
    width, height = max(left + nx * size + 20, 480), top + ny * size + 60
    values: dict[str, float] = {k: c["fitness"] for k, c in state["cells"].items()}
    label = "dev"
    if holdout is not None:
        values = {e["cell"]: e["holdout_fitness"] for e in holdout["elites"]}
        label = "holdout"
    hi = max(values.values(), default=0.0) or 1.0
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="11">',
        f'<rect width="{width}" height="{height}" fill="#fff"/>',
        f'<text x="14" y="18" font-size="13">{state["identity"]["problem"]}</text>',
        f'<text x="14" y="36" font-size="12">kills per 1,000 ticks ({label})</text>',
    ]
    for key, v in sorted(values.items()):
        i, j = map(int, key.split(","))
        x, y = left + i * size, top + (ny - 1 - j) * size
        shade = int(235 - 190 * max(0.0, v) / hi)
        ink = "#fff" if shade < 140 else "#222"
        parts.append(
            f'<rect x="{x}" y="{y}" width="{size - 2}" height="{size - 2}" rx="3" '
            f'fill="rgb({shade},{shade + 8},{min(255, shade + 30)})"><title>cell {key}: '
            f"{v:.3f}</title></rect>"
        )
        parts.append(
            f'<text x="{x + size / 2 - 1}" y="{y + size / 2 + 3}" text-anchor="middle" '
            f'fill="{ink}">{v:.2f}</text>'
        )
    if holdout is not None:
        i, j = map(int, holdout["baseline"]["cell"].split(","))
        x, y = left + i * size, top + (ny - 1 - j) * size
        parts.append(
            f'<rect x="{x - 1}" y="{y - 1}" width="{size}" height="{size}" fill="none" '
            'stroke="#d33" stroke-width="2"><title>hand-set snake</title></rect>'
        )
    gx0, gy1 = left, top + ny * size
    parts += [
        f'<text x="{gx0}" y="{gy1 + 16}">{ax["low"]:g}</text>',
        f'<text x="{gx0 + nx * size - 2}" y="{gy1 + 16}" text-anchor="end">{ax["high"]:g}+</text>',
        f'<text x="{gx0 + nx * size / 2}" y="{gy1 + 32}" text-anchor="middle">'
        "mean distance to nearest enemy head (low = aggressive)</text>",
        f'<text x="{left - 6}" y="{gy1}" text-anchor="end">{ay["low"]:g}</text>',
        f'<text x="{left - 6}" y="{top + 10}" text-anchor="end">{ay["high"]:g}+</text>',
        f'<text x="14" y="{top + ny * size / 2}" text-anchor="middle" '
        f'transform="rotate(-90 14 {top + ny * size / 2})">'
        "reachable cells (high = cautious)</text>",
    ]
    if holdout is not None:
        parts.append(
            f'<text x="{left}" y="{gy1 + 48}">red outline: the hand-set snake '
            f"({holdout['baseline']['fitness']:.3f} on the same holdout seeds)</text>"
        )
    parts.append("</svg>")
    return "\n".join(parts)
