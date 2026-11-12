"""Command line entry points: ``python -m arena.cli <command> --help``."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from arena.agents import DEFAULT_POLICY, LINEUPS, POLICIES, make_policy
from arena.agents.registry import expand_policies
from arena.engine import GameConfig
from arena.sim.match import Match, MatchResult


def add_game_options(
    parser: argparse.ArgumentParser, d: GameConfig | None = None, policy: str = DEFAULT_POLICY
) -> None:
    d = d or GameConfig()
    g = parser.add_argument_group("game settings")
    g.add_argument("--width", type=int, default=d.width, help="board width (default %(default)s)")
    g.add_argument("--height", type=int, default=d.height, help="board height (%(default)s)")
    g.add_argument(
        "--snakes", type=int, default=d.num_snakes, help="number of snakes (%(default)s)"
    )
    g.add_argument("--length", type=int, default=d.snake_length, help="snake length (%(default)s)")
    g.add_argument(
        "--target", type=int, default=d.score_target, help="kills needed to win (%(default)s)"
    )
    g.add_argument(
        "--max-ticks", type=int, default=d.max_ticks, help="tick cap (default %(default)s)"
    )
    g.add_argument(
        "--respawn", type=int, default=d.respawn_delay, help="respawn delay (%(default)s)"
    )
    g.add_argument(
        "--policy",
        default=policy,
        help="one policy for every snake, a comma list per snake, or a lineup "
        f"({', '.join([*POLICIES, *LINEUPS])})",
    )


def config_from(args: argparse.Namespace) -> GameConfig:
    return GameConfig(
        width=args.width,
        height=args.height,
        num_snakes=args.snakes,
        snake_length=args.length,
        score_target=args.target,
        max_ticks=args.max_ticks,
        respawn_delay=args.respawn,
    )


def policy_names(spec: str, count: int) -> list[str]:
    return expand_policies(spec, count)


def describe(config: GameConfig) -> str:
    return (
        f"{config.width}x{config.height} board, {config.num_snakes} snakes x "
        f"{config.snake_length} cells, first to {config.score_target} kills, "
        f"cap {config.max_ticks:,} ticks"
    )


def format_result(result: MatchResult) -> str:
    lines = [
        f"Match seed {result.seed}: {describe(result.config)}",
        f"Ended at tick {result.ticks:,} ({result.end_reason})"
        + (f", winner {result.winner}" if result.winner else ", no single winner"),
        "",
        f"{'rank':>4}  {'snake':<5}  {'policy':<15} {'kills':>5} {'deaths':>6} "
        f"{'K/D':>6} {'alive ticks':>11}",
    ]
    names = dict(zip(result.config.snake_ids, result.policies, strict=True))
    for s in result.standings:
        kd = s.kills / s.deaths if s.deaths else float(s.kills)
        lines.append(
            f"{s.rank:>4}  {s.snake:<5}  {names[s.snake]:<15} {s.kills:>5} {s.deaths:>6} "
            f"{kd:>6.2f} {s.alive_ticks:>11,}"
        )
    causes = {k: v for k, v in result.death_causes.items() if v}
    if causes:
        lines.append("")
        lines.append("deaths by cause:")
        for sid, counts in causes.items():
            parts = ", ".join(f"{c} {n}" for c, n in sorted(counts.items(), key=lambda x: -x[1]))
            lines.append(f"  {sid}: {parts}")
    return "\n".join(lines)


def cmd_run_match(args: argparse.Namespace) -> int:
    from arena.sim.replay import build_replay, save_replay

    config = config_from(args)
    names = policy_names(args.policy, config.num_snakes)
    match = Match([make_policy(n) for n in names], args.seed, config, record=bool(args.replay))
    started = time.perf_counter()
    every = args.progress
    while not match.finished:
        match.advance()
        if every and match.state.tick % every == 0:
            scores = " ".join(f"{s.id}:{s.kills}" for s in match.state.snakes)
            print(f"  tick {match.state.tick:,}  {scores}", file=sys.stderr)
    elapsed = time.perf_counter() - started
    result = match.result()
    if args.json:
        import json

        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_result(result))
        print(f"\n{result.ticks:,} ticks in {elapsed:.2f}s ({result.ticks / elapsed:,.0f} ticks/s)")
    if args.replay:
        save_replay(build_replay(match), args.replay)
        print(f"replay written to {args.replay}", file=sys.stderr)
    return 0


def cmd_run_tournament(args: argparse.Namespace) -> int:
    from arena.sim.tournament import (
        matrix_csv,
        run_matches,
        summarise,
        summary_csv,
        total_kill_matrix,
        write_outputs,
    )

    config = config_from(args)
    names = policy_names(args.policy, config.num_snakes)
    seeds = range(args.seed_start, args.seed_start + args.matches)
    print(f"{args.matches} matches: {describe(config)}", file=sys.stderr)
    started = time.perf_counter()
    results = []
    for i, r in enumerate(run_matches(names, seeds, config, args.workers), 1):
        results.append(r)
        if args.verbose:
            print(
                f"  [{i}/{args.matches}] seed {r.seed}: {r.ticks:,} ticks, {r.end_reason}, "
                f"winner {r.winner or '-'}",
                file=sys.stderr,
            )
    elapsed = time.perf_counter() - started
    print(summary_csv(summarise(results)), end="")
    print()
    print(matrix_csv(total_kill_matrix(results)), end="")
    total_ticks = sum(r.ticks for r in results)
    print(f"\n{total_ticks:,} ticks in {elapsed:.1f}s", file=sys.stderr)
    if args.out:
        write_outputs(Path(args.out), results)
        print(f"results written to {args.out}", file=sys.stderr)
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    from arena.sim.bench import decision_report, decision_times, run_bench

    config = config_from(args)
    if args.policies:
        spec = "personalities" if args.policies == "all" else args.policies
        names = policy_names(spec, config.num_snakes)
        report, ok = decision_report(decision_times(config, args.ticks, args.seed, names))
        print(report)
        return 0 if ok else 1
    print(run_bench(config, args.ticks, args.seed, policy_names(args.policy, config.num_snakes)))
    return 0


def cmd_check_personalities(args: argparse.Namespace) -> int:
    from arena.sim.personality_check import episode_config, run_check

    config = episode_config(args.width, args.height, args.ticks)
    report = run_check(
        args.matches,
        config,
        args.workers,
        args.seed_start,
        progress=lambda msg: print(msg, file=sys.stderr),
    )
    text = report.to_markdown()
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
        print(f"report written to {args.out}", file=sys.stderr)
    return 0 if report.passed else 1


def cmd_watch(args: argparse.Namespace) -> int:
    from arena.viz.server import serve

    config = config_from(args)
    policy_names(args.policy, config.num_snakes)
    return serve(
        host=args.host,
        port=args.port,
        config=config,
        seed=args.seed,
        policy=args.policy,
        replay_path=args.replay,
        open_browser=not args.no_browser,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arena", description="Snake Arena RSI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run-match", help="simulate one headless match and print standings")
    add_game_options(p)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--replay", help="write a replay JSON file to this path")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.add_argument("--progress", type=int, default=0, help="print scores every N ticks")
    p.set_defaults(func=cmd_run_match)

    p = sub.add_parser("run-tournament", help="simulate many seeded matches")
    add_game_options(p)
    p.add_argument("--matches", type=int, default=100)
    p.add_argument("--seed-start", type=int, default=0)
    p.add_argument("--workers", type=int, default=1, help="processes (results do not change)")
    p.add_argument("--out", help="directory for matches.jsonl, summary.csv, kill_matrix.csv")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_run_tournament)

    p = sub.add_parser("bench", help="measure engine and match speed")
    add_game_options(p)
    p.add_argument("--ticks", type=int, default=20_000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--policies",
        help="time each policy's decisions instead: 'all' for the five personalities, "
        "or a lineup / comma list as for --policy",
    )
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser(
        "check-personalities", help="run the phase 2 acceptance tournaments and report"
    )
    p.add_argument("--matches", type=int, default=100)
    p.add_argument("--ticks", type=int, default=5000, help="episode length (%(default)s)")
    p.add_argument("--width", type=int, default=100)
    p.add_argument("--height", type=int, default=100)
    p.add_argument("--seed-start", type=int, default=0)
    p.add_argument("--workers", type=int, default=1, help="processes (results do not change)")
    p.add_argument("--out", help="also write the markdown report to this file")
    p.set_defaults(func=cmd_check_personalities)

    p = sub.add_parser("watch", help="open the browser viewer (live match or replay)")
    from arena.viz.server import VIEWER_DEFAULTS, VIEWER_POLICY

    add_game_options(p, VIEWER_DEFAULTS, VIEWER_POLICY)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--replay", help="open this replay file instead of a live match")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    p.set_defaults(func=cmd_watch)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
    except ValueError as exc:
        parser.error(str(exc))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
