"""Phase 2 acceptance: do the five personalities beat RandomSafe and behave differently?

Runs the tournaments that phase 2 spec section 5 asks for, all on the same seeds:

1. all five personalities together, and five ``RandomSafe`` snakes as the baseline;
2. each personality in seat ``s0`` against four ``RandomSafe`` snakes.

Matches are fixed-length evaluation episodes (no win target), so every match contributes
the same number of ticks.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from arena.agents.registry import PERSONALITIES
from arena.engine import GameConfig
from arena.sim.match import MatchResult
from arena.sim.stats import bootstrap_mean_ci, mean
from arena.sim.tournament import SnakeSummary, run_matches, summarise

BASELINE = "random_safe"


def episode_config(width: int = 100, height: int = 100, ticks: int = 5000) -> GameConfig:
    return GameConfig(width=width, height=height, max_ticks=ticks, score_target=10**9)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class CheckReport:
    config: GameConfig
    matches: int
    all_five: list[SnakeSummary]
    baseline: list[SnakeSummary]
    versus: dict[str, dict[str, Any]] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_markdown(self) -> str:
        c = self.config
        lines = [
            f"# Phase 2 personality check ({self.matches} matches per tournament)",
            "",
            f"{c.width} x {c.height} board, {c.num_snakes} snakes x {c.snake_length}, "
            f"{c.max_ticks:,}-tick episodes, no win target.",
            "",
            "## All five personalities together",
            "",
            _table(self.all_five),
            "",
            "## Baseline: five RandomSafe snakes",
            "",
            _table(self.baseline),
            "",
            "## Each personality against four RandomSafe snakes",
            "",
            "| personality | kills/1k ticks | RandomSafe mean | difference | 95% CI |",
            "|---|---|---|---|---|",
        ]
        for name, v in self.versus.items():
            lines.append(
                f"| {name} | {v['kills']:.3f} | {v['baseline_kills']:.3f} | "
                f"{v['difference']:+.3f} | [{v['ci'][0]:+.3f}, {v['ci'][1]:+.3f}] |"
            )
        lines += ["", "## Acceptance", ""]
        lines += [f"- {'PASS' if k.passed else 'FAIL'} {k.name}: {k.detail}" for k in self.checks]
        lines += ["", f"Overall: {'PASS' if self.passed else 'FAIL'}", ""]
        return "\n".join(lines)


def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.2f}"


def _table(summaries: Sequence[SnakeSummary]) -> str:
    rows = [
        "| snake | policy | kills/1k alive | deaths/1k alive | K/D | enemy distance | "
        "reachable space | deaths: wall / self / body / head-on / swap |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        causes = " / ".join(
            str(s.death_causes.get(c, 0)) for c in ("wall", "self", "body", "head_on", "head_swap")
        )
        rows.append(
            f"| {s.snake} | {s.policy} | {s.kills_per_1000_alive:.3f} | "
            f"{s.deaths_per_1000_alive:.3f} | {s.kd:.2f} | "
            f"{_fmt(s.behaviour.mean_enemy_distance)} | {_fmt(s.behaviour.mean_space)} | {causes} |"
        )
    return "\n".join(rows)


def _kills_per_1000(result: MatchResult, snake: str) -> float:
    standing = next(s for s in result.standings if s.snake == snake)
    return 1000 * standing.kills / result.ticks if result.ticks else 0.0


def run_check(
    matches: int = 100,
    config: GameConfig | None = None,
    workers: int = 1,
    seed_start: int = 0,
    progress: Callable[[str], None] = lambda _: None,
) -> CheckReport:
    config = config or episode_config()
    if config.num_snakes != len(PERSONALITIES):
        raise ValueError(f"the check needs {len(PERSONALITIES)} snakes")
    seeds = range(seed_start, seed_start + matches)
    ids = config.snake_ids

    def play(names: Sequence[str]) -> list[MatchResult]:
        progress(f"playing {', '.join(names)}")
        return list(run_matches(names, seeds, config, workers))

    all_five = summarise(play(PERSONALITIES))
    baseline = summarise(play([BASELINE] * len(ids)))
    report = CheckReport(config, matches, all_five, baseline)

    for name in PERSONALITIES:
        results = play([name] + [BASELINE] * (len(ids) - 1))
        diffs = [
            _kills_per_1000(r, ids[0]) - mean([_kills_per_1000(r, sid) for sid in ids[1:]])
            for r in results
        ]
        summary = summarise(results)
        report.versus[name] = {
            "kills": summary[0].kills_per_1000_ticks,
            "baseline_kills": mean([s.kills_per_1000_ticks for s in summary[1:]]),
            "difference": mean(diffs),
            "ci": bootstrap_mean_ci(diffs),
        }

    base_deaths = mean([s.deaths_per_1000_alive for s in baseline])
    for s in all_five:
        report.checks.append(
            Check(
                f"{s.policy} dies less than RandomSafe",
                s.deaths_per_1000_alive < base_deaths,
                f"{s.deaths_per_1000_alive:.3f} vs {base_deaths:.3f} deaths per 1,000 alive ticks",
            )
        )
    for name, v in report.versus.items():
        lo, hi = v["ci"]
        report.checks.append(
            Check(
                f"{name} out-kills RandomSafe",
                v["difference"] > 0 and lo > 0,
                f"+{v['difference']:.3f} kills per 1,000 ticks, 95% CI [{lo:+.3f}, {hi:+.3f}]",
            )
        )
    by_name = {s.policy: s for s in all_five}
    distance = {n: by_name[n].behaviour.mean_enemy_distance or 0.0 for n in by_name}
    space = {n: by_name[n].behaviour.mean_space or 0.0 for n in by_name}
    deaths = {n: by_name[n].deaths_per_1000_alive for n in by_name}
    report.checks += [
        Check(
            "hunter has the lowest mean distance to enemy heads",
            min(distance, key=lambda n: distance[n]) == "hunter",
            ", ".join(f"{n} {v:.1f}" for n, v in distance.items()),
        ),
        Check(
            "survivor has the highest mean reachable space",
            max(space, key=lambda n: space[n]) == "survivor",
            ", ".join(f"{n} {v:.1f}" for n, v in space.items()),
        ),
        Check(
            "survivor has the fewest deaths",
            deaths["survivor"] <= min(deaths.values()),
            ", ".join(f"{n} {v:.3f}" for n, v in deaths.items()),
        ),
    ]
    return report
