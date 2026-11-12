"""The phase 4 report (phase 4 spec, section 5).

Everything is measured on each lineage's **final** seeds, which no decision during the
run ever saw. ``build`` plays the extra games and stores every per-seed number in
``report.json``; ``render`` turns that file into ``report.md`` and ``progress.svg``
without playing anything, so the written numbers can always be recomputed from it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from arena.agents.registry import PERSONALITIES, STYLES
from arena.engine import GameConfig
from arena.evolution.entrants import Entrant
from arena.evolution.evaluator import SnakeEvaluator, Workers
from arena.evolution.run import Profile, make_context
from arena.rsi.accept import bootstrap_ci
from arena.rsi.seeds import rng_for
from arena.rsi.store import read_json, write_atomic, write_json
from arena.rsi.types import Candidate
from arena.sim.match import Match

METRICS_EVERY = 50


@dataclass
class LineageView:
    """One lineage read back from disk, without opening it for writing."""

    name: str
    records: list[dict[str, Any]]
    hall: list[tuple[int, Candidate]]
    final_seeds: tuple[int, ...]

    def champion_at(self, generation: int) -> tuple[int, Candidate]:
        """(version, champion) after ``generation``; versions count from 1."""
        version, champ = 1, self.hall[0][1]
        for v, (g, c) in enumerate(self.hall, start=1):
            if g <= generation:
                version, champ = v, c
        return version, champ


def load_lineage(directory: Path) -> LineageView:
    config = read_json(directory / "config.json")
    baseline = Candidate.from_dict(config["identity"]["baseline"])
    records = [json.loads(x) for x in (directory / "generations.jsonl").read_text().splitlines()]
    checkpoint = read_json(directory / "checkpoint.json")
    records = records[: checkpoint["generation"]]
    hall = [(0, baseline)]
    for rec in records:
        if rec["decision"]["accept"]:
            data = read_json(directory / "archive" / f"{rec['champion_after']}.json")
            hall.append((rec["generation"], Candidate.from_dict(data)))
    seeds = tuple(read_json(directory / "seeds.json")["final"])
    return LineageView(directory.name, records, hall, seeds)


def load_run(run_dir: Path) -> tuple[Profile, dict[str, LineageView]]:
    meta = read_json(run_dir / "evolution.json")["identity"]
    profile = Profile.from_dict(meta["profile"])
    views = {n: load_lineage(run_dir / "lineages" / n) for n in meta["lineages"]}
    return profile, views


@dataclass(frozen=True)
class GameTask:
    config: GameConfig
    seed: int
    entrants: tuple[Entrant, ...]


def play_game(task: GameTask) -> dict[str, Any]:
    match = Match(
        [e.build() for e in task.entrants], task.seed, task.config, metrics_every=METRICS_EVERY
    )
    r = match.run()
    by_id = {s.snake: s for s in r.standings}
    snakes = []
    for sid in task.config.snake_ids:
        b = r.behaviour[sid]
        snakes.append(
            {
                "kills": by_id[sid].kills,
                "deaths": by_id[sid].deaths,
                "distance": b.mean_enemy_distance,
                "space": b.mean_space,
            }
        )
    return {"snakes": snakes, "kill_matrix": r.kill_matrix}


def _ci(values: Sequence[float], seed: int, purpose: str) -> list[float]:
    lo, hi = bootstrap_ci(np.asarray(values, dtype=float), rng_for(seed, 0, purpose), 2000)
    return [lo, hi]


def _mean(values: Sequence[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def build(run_dir: str | Path, workers: int | None = None) -> dict[str, Any]:
    """Play the report's games and write ``report.json``; returns its content."""
    run_dir = Path(run_dir)
    profile, views = load_run(run_dir)
    final_path = run_dir / "final.json"
    if not final_path.exists():
        raise ValueError(f"{run_dir} has not finished; run evolve to the end first")
    final = read_json(final_path)
    config = profile.settings.config()
    per_k = 1000 / profile.settings.ticks
    halls = {n: [c for _, c in v.hall] for n, v in views.items()}
    ctx = make_context(halls)
    reference = ctx.reference
    out: dict[str, Any] = {
        "profile": profile.to_dict(),
        "generation": final["generation"],
        "stop_reason": final["stop_reason"],
        "lineages": {},
    }
    with Workers(workers) as pool:
        for name, view in views.items():
            me = PERSONALITIES.index(name)
            progress = []
            for version, (gen, cand) in enumerate(view.hall, start=1):
                ent = Entrant.personality(name, cand.params, version)
                tasks = []
                for seed in view.final_seeds:
                    lineup = [r for j, r in enumerate(reference) if j != me]
                    lineup.insert(seed % 5, ent)
                    tasks.append(GameTask(config, seed, tuple(lineup)))
                games = pool.map(play_game, tasks)
                mine = [g["snakes"][t.seed % 5] for g, t in zip(games, tasks, strict=True)]
                kills = [m["kills"] * per_k for m in mine]
                progress.append(
                    {
                        "version": version,
                        "generation": gen,
                        "candidate": cand.id,
                        "kills_per_1k": kills,
                        "mean": sum(kills) / len(kills),
                        "ci": _ci(kills, version, f"progress-{name}"),
                        "deaths": sum(m["deaths"] for m in mine) / len(mine),
                        "enemy_distance": _mean([m["distance"] for m in mine]),
                        "space": _mean([m["space"] for m in mine]),
                    }
                )
            cycle = []
            last_version = len(view.hall)
            if last_version > 1:
                settings = replace(profile.settings, shares=(0.0, 1.0, 0.0, 0.0))
                ev = SnakeEvaluator(
                    name,
                    settings,
                    pool,
                    ctx,
                    {c.id: v for v, (_, c) in enumerate(view.hall, start=1)},
                )
                champ = view.hall[-1][1]
                for version, (_, earlier) in enumerate(view.hall[:-1], start=1):
                    r = ev.evaluate(champ, earlier, view.final_seeds)
                    cycle.append(
                        {
                            "versus": version,
                            "diffs": r.diffs.tolist(),
                            "mean_diff": r.mean_diff,
                            "ci": _ci(r.diffs.tolist(), version, f"cycle-{name}"),
                        }
                    )
            out["lineages"][name] = {
                "versions": last_version,
                "accepted": sum(1 for rec in view.records if rec["decision"]["accept"]),
                "generations": len(view.records),
                "final": final["lineages"][name]["final"],
                "progress": progress,
                "cycle_check": cycle,
                "decisions": [_decision(rec) for rec in view.records],
            }
        seeds = next(iter(views.values())).final_seeds
        champions = tuple(ctx.champions)
        games = pool.map(play_game, [GameTask(config, s, champions) for s in seeds])
    ids = config.snake_ids
    matrix = {k: {v: sum(g["kill_matrix"][k][v] for g in games) for v in ids} for k in ids}
    out["matrix"] = {
        "snakes": [e.label for e in champions],
        "episodes": len(games),
        "ticks": profile.settings.ticks,
        "kills": [[matrix[a][b] for b in ids] for a in ids],
    }
    write_json(run_dir / "report.json", out)
    return out


def clean_note(note: str) -> str:
    """The change list of a note without "x 20->20" entries, which are float noise from the
    unit round trip rather than changes (notes written before proposers dropped them)."""
    kept = []
    for part in note.split(": ", 1)[-1].split(", "):
        old, sep, new = part.rpartition(" ")[2].partition("->")
        if not sep or f"{float(old):.4g}" != f"{float(new):.4g}":
            kept.append(part)
    return ", ".join(kept) or "no change"


def _decision(rec: Mapping[str, Any]) -> dict[str, Any]:
    d = rec["decision"]
    chosen = next((f for f in rec["feedback"] if f["candidate"]["id"] == rec["chosen"]), None)
    stats = d.get("stats", {})
    return {
        "generation": rec["generation"],
        "change": clean_note(chosen["candidate"]["note"]) if chosen else "-",
        "dev": stats.get("dev"),
        "holdout": stats.get("holdout"),
        "guards": stats.get("guards"),
        "accept": d["accept"],
        "stage": d["stage"],
        "rationale": d["rationale"],
    }


# -- rendering ------------------------------------------------------------------------


def _fmt_ci(ci: Sequence[float] | None) -> str:
    return f"[{ci[0]:+.3f}, {ci[1]:+.3f}]" if ci else "-"


def verdict(final: Mapping[str, Any] | None) -> str:
    if final is None:
        return "no change (nothing accepted)"
    lo, hi = final["ci"]
    if lo > 0:
        return "improved"
    if hi < 0:
        return "got worse"
    return "no significant change"


def _ordered(lineages: Mapping[str, Any]) -> dict[str, Any]:
    """JSON files sort their keys; reports list snakes in seat order."""
    return {n: lineages[n] for n in PERSONALITIES if n in lineages}


def render(run_dir: str | Path) -> str:
    run_dir = Path(run_dir)
    data = read_json(run_dir / "report.json")
    data["lineages"] = _ordered(data["lineages"])
    p = data["profile"]
    s = p["settings"]
    label = (
        ""
        if p["name"] == "default"
        else f" — **{p['name']} profile: a reduced setting, not the specified experiment**"
    )
    lines = [
        f"# Phase 4 report: {run_dir.name}",
        "",
        f"Profile `{p['name']}`{label}. {s['width']} x {s['height']} board, "
        f"{s['ticks']:,}-tick episodes, {p['dev_pairs']} dev + {p['holdout_pairs']} holdout "
        f"pairs per candidate, proposer `{p['proposer']}`, min gain {p['min_rel_gain']:.0%}, "
        f"patience {p['patience']}. Stopped after generation {data['generation']} "
        f"({data['stop_reason']}).",
        "",
        "All numbers below are on each lineage's final seeds, which no decision saw.",
        "",
        "## Did each snake improve? (evolved champion vs its generation-0 self)",
        "",
        "Paired games on the final seeds against the run's opponent mixture; kills per "
        "1,000 ticks.",
        "",
        "| snake | accepted | champion | evolved | gen 0 | difference | 95% CI | verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, lin in data["lineages"].items():
        f = lin["final"]
        disp = STYLES[name][0]
        if f is None:
            lines.append(f"| {disp} | 0 | v1 | - | - | - | - | {verdict(None)} |")
        else:
            lines.append(
                f"| {disp} | {lin['accepted']} | v{lin['versions']} | {f['mean_cand']:.3f} | "
                f"{f['mean_champ']:.3f} | {f['diff']:+.3f} | {_fmt_ci(f['ci'])} | "
                f"{verdict(f)} |"
            )
    lines += [
        "",
        "## Progress against the reference portfolio",
        "",
        "Each champion version in its seat against the four hand-set personalities.",
        "",
        "![progress](progress.svg)",
        "",
        "| snake | version | from generation | kills/1k | 95% CI | deaths/episode | "
        "enemy distance | space |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, lin in data["lineages"].items():
        for pr in lin["progress"]:
            lines.append(
                f"| {STYLES[name][0]} | v{pr['version']} | {pr['generation']} | "
                f"{pr['mean']:.3f} | {_fmt_ci(pr['ci'])} | {pr['deaths']:.2f} | "
                f"{_opt(pr['enemy_distance'])} | {_opt(pr['space'])} |"
            )
    lines += [
        "",
        "## Hall-of-fame check",
        "",
        "Each final champion against every earlier version of itself, paired, with "
        "opponents drawn from all lineages' halls of fame. A negative interval would mean "
        "a later version lost to an earlier one (a cycle).",
        "",
    ]
    rows = [
        f"| {STYLES[n][0]} | v{lin['versions']} | v{c['versus']} | {c['mean_diff']:+.3f} | "
        f"{_fmt_ci(c['ci'])} |"
        for n, lin in data["lineages"].items()
        for c in lin["cycle_check"]
    ]
    if rows:
        lines += [
            "| snake | final | versus | difference | 95% CI |",
            "|---|---|---|---|---|",
            *rows,
        ]
    else:
        lines.append("No lineage has more than one version, so there is nothing to check.")
    m = data["matrix"]
    lines += [
        "",
        f"## Kill matrix of the final champions ({m['episodes']} episodes of {m['ticks']:,} ticks)",
        "",
        "Rows killed columns.",
        "",
        "| killer \\ victim | " + " | ".join(m["snakes"]) + " |",
        "|---|" + "---|" * len(m["snakes"]),
    ]
    for label, row in zip(m["snakes"], m["kills"], strict=True):
        lines.append(f"| {label} | " + " | ".join(str(x) for x in row) + " |")
    lines += ["", "## Decision log", ""]
    for name, lin in data["lineages"].items():
        lines += [
            f"### {STYLES[name][0]}",
            "",
            "| gen | change | dev diff | holdout diff | holdout CI | decision |",
            "|---|---|---|---|---|---|",
        ]
        for d in lin["decisions"]:
            dev = d["dev"]["diff"] if d["dev"] else None
            hold = d["holdout"] or {}
            mark = "**accept**" if d["accept"] else "reject"
            lines.append(
                f"| {d['generation']} | {_cell(d['change'])} | {_opt(dev, '+.3f')} | "
                f"{_opt(hold.get('diff'), '+.3f')} | {_fmt_ci(hold.get('ci'))} | "
                f"{mark}: {_cell(d['rationale'])} |"
            )
        lines.append("")
    return "\n".join(lines)


def _opt(x: float | None, fmt: str = ".2f") -> str:
    return "-" if x is None else format(x, fmt)


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def progress_svg(data: Mapping[str, Any]) -> str:
    """Small multiples: one panel per snake, champion kills/1k over generations with its
    95% band, all on one shared y scale."""
    lins = _ordered(data["lineages"])
    last = max(1, int(data["generation"]))
    top = 1.1 * max([float(pr["ci"][1]) for lin in lins.values() for pr in lin["progress"]] + [0.1])
    pw, ph, pad, left, head = 220, 150, 16, 40, 28
    width = left + len(lins) * (pw + pad)
    height = head + ph + 40
    ink, muted, grid, band, line = "#1f2328", "#59636e", "#d0d7de", "#c8d7f0", "#2f5fb3"
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui, sans-serif" font-size="11">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
    ]

    def y(v: float) -> float:
        return head + ph - v / top * ph

    for k in (0.0, top / 2, top):
        out.append(
            f'<text x="{left - 6}" y="{y(k) + 4:.1f}" text-anchor="end" fill="{muted}">'
            f"{k:.2f}</text>"
        )
    for i, (name, lin) in enumerate(lins.items()):
        x0 = left + i * (pw + pad)

        def x(g: float, x0: float = x0) -> float:
            return x0 + g / last * pw

        out.append(f'<text x="{x0}" y="16" fill="{ink}" font-weight="600">{STYLES[name][0]}</text>')
        for k in (0.0, top / 2, top):
            out.append(
                f'<line x1="{x0}" x2="{x0 + pw}" y1="{y(k):.1f}" y2="{y(k):.1f}" '
                f'stroke="{grid}" stroke-width="1"/>'
            )
        steps = []
        prog = lin["progress"]
        for j, pr in enumerate(prog):
            end = prog[j + 1]["generation"] if j + 1 < len(prog) else last
            steps.append((pr["generation"], end, pr))
        upper = " ".join(
            f"{x(a):.1f},{y(pr['ci'][1]):.1f} {x(b):.1f},{y(pr['ci'][1]):.1f}" for a, b, pr in steps
        )
        lower = " ".join(
            f"{x(b):.1f},{y(pr['ci'][0]):.1f} {x(a):.1f},{y(pr['ci'][0]):.1f}"
            for a, b, pr in reversed(steps)
        )
        out.append(f'<polygon points="{upper} {lower}" fill="{band}" opacity="0.8"/>')
        pts = " ".join(
            f"{x(a):.1f},{y(pr['mean']):.1f} {x(b):.1f},{y(pr['mean']):.1f}" for a, b, pr in steps
        )
        out.append(
            f'<polyline points="{pts}" fill="none" stroke="{line}" stroke-width="2" '
            'stroke-linejoin="round"/>'
        )
        for a, _, pr in steps:
            out.append(
                f'<circle cx="{x(a):.1f}" cy="{y(pr["mean"]):.1f}" r="4" fill="{line}" '
                f'stroke="#ffffff" stroke-width="2"><title>v{pr["version"]} from '
                f"generation {a}: {pr['mean']:.3f} kills/1k</title></circle>"
            )
        for g in (0, last):
            out.append(
                f'<text x="{x(g):.1f}" y="{head + ph + 16}" text-anchor="middle" '
                f'fill="{muted}">{g}</text>'
            )
    out.append(
        f'<text x="{left}" y="{height - 6}" fill="{muted}">generation → ; '
        "y: kills per 1,000 ticks vs the reference portfolio (band: 95% CI)</text>"
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write(run_dir: str | Path, workers: int | None = None, rebuild: bool = False) -> Path:
    """Build ``report.json`` if missing (or ``rebuild``), then write report.md and the chart."""
    run_dir = Path(run_dir)
    if rebuild or not (run_dir / "report.json").exists():
        build(run_dir, workers)
    data = read_json(run_dir / "report.json")
    write_atomic(run_dir / "progress.svg", progress_svg(data))
    path = run_dir / "report.md"
    write_atomic(path, render(run_dir) + "\n")
    return path
