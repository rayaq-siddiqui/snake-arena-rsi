"""Many seeded matches, optionally across processes, with per-snake summaries."""

from __future__ import annotations

import csv
import io
import json
import multiprocessing
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.agents import make_policy
from arena.engine import GameConfig
from arena.sim.match import MatchResult, simulate_match


@dataclass(frozen=True)
class SnakeSummary:
    snake: str
    policy: str
    matches: int
    wins: int
    kills: int
    deaths: int
    alive_ticks: int
    match_ticks: int

    @property
    def kills_per_1000_ticks(self) -> float:
        return 1000 * self.kills / self.match_ticks if self.match_ticks else 0.0

    @property
    def kd(self) -> float:
        return self.kills / self.deaths if self.deaths else float(self.kills)

    def row(self) -> dict[str, Any]:
        return {
            "snake": self.snake,
            "policy": self.policy,
            "matches": self.matches,
            "wins": self.wins,
            "mean_kills": round(self.kills / self.matches, 4),
            "mean_deaths": round(self.deaths / self.matches, 4),
            "kd": round(self.kd, 4),
            "kills_per_1000_ticks": round(self.kills_per_1000_ticks, 4),
            "alive_share": round(self.alive_ticks / self.match_ticks, 4),
        }


def _play(job: tuple[tuple[str, ...], int, dict[str, int]]) -> MatchResult:
    names, seed, config = job
    return simulate_match([make_policy(n) for n in names], seed, GameConfig.from_dict(config))


def run_matches(
    policy_names: Sequence[str], seeds: Sequence[int], config: GameConfig, workers: int = 1
) -> Iterator[MatchResult]:
    """Yield results in seed order; the output never depends on ``workers``."""
    jobs = [(tuple(policy_names), seed, config.to_dict()) for seed in seeds]
    if workers <= 1:
        yield from map(_play, jobs)
        return
    with multiprocessing.get_context("spawn").Pool(workers) as pool:
        yield from pool.imap(_play, jobs, chunksize=1)


def summarise(results: Sequence[MatchResult]) -> list[SnakeSummary]:
    if not results:
        return []
    ids = results[0].config.snake_ids
    summaries = []
    for i, sid in enumerate(ids):
        mine = [next(s for s in r.standings if s.snake == sid) for r in results]
        summaries.append(
            SnakeSummary(
                snake=sid,
                policy=results[0].policies[i],
                matches=len(results),
                wins=sum(r.winner == sid for r in results),
                kills=sum(s.kills for s in mine),
                deaths=sum(s.deaths for s in mine),
                alive_ticks=sum(s.alive_ticks for s in mine),
                match_ticks=sum(r.ticks for r in results),
            )
        )
    return summaries


def total_kill_matrix(results: Sequence[MatchResult]) -> dict[str, dict[str, int]]:
    ids = results[0].config.snake_ids if results else ()
    matrix = {k: {v: 0 for v in ids} for k in ids}
    for r in results:
        for killer, row in r.kill_matrix.items():
            for victim, n in row.items():
                matrix[killer][victim] += n
    return matrix


def summary_csv(summaries: Sequence[SnakeSummary]) -> str:
    out = io.StringIO()
    rows = [s.row() for s in summaries]
    if rows:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return out.getvalue()


def matrix_csv(matrix: dict[str, dict[str, int]]) -> str:
    ids = list(matrix)
    lines = ["killer\\victim," + ",".join(ids)]
    lines += [k + "," + ",".join(str(matrix[k][v]) for v in ids) for k in ids]
    return "\n".join(lines) + "\n"


def write_outputs(out_dir: Path, results: Sequence[MatchResult]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "matches.jsonl").open("w") as f:
        for r in results:
            f.write(json.dumps(r.to_dict(), sort_keys=True) + "\n")
    (out_dir / "summary.csv").write_text(summary_csv(summarise(results)))
    (out_dir / "kill_matrix.csv").write_text(matrix_csv(total_kill_matrix(results)))
