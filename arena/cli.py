"""Command line entry points: ``python -m arena.cli <command> --help``."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from arena.agents import DEFAULT_POLICY, LINEUPS, POLICIES, make_policy
from arena.agents.registry import expand_policies
from arena.engine import GameConfig
from arena.sim.match import Match, MatchResult

if TYPE_CHECKING:
    from arena.rsi.types import Proposer


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
    from arena.sim.bench import decision_report, decision_times, parallel_report, run_bench

    config = config_from(args)
    if args.policies:
        spec = "personalities" if args.policies == "all" else args.policies
        names = policy_names(spec, config.num_snakes)
        report, ok = decision_report(decision_times(config, args.ticks, args.seed, names))
        print(report)
        return 0 if ok else 1
    names = policy_names(args.policy, config.num_snakes)
    print(run_bench(config, args.ticks, args.seed, names))
    if args.workers > 1:
        print(parallel_report(config, args.ticks, args.seed, names, args.workers))
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
    from arena.viz.server import NO_ROSTER, VIEWER_POLICY, serve

    config = config_from(args)
    roster, policy = NO_ROSTER, args.policy
    if args.run:
        from arena.evolution.watch import run_roster

        roster, first = run_roster(args.run, args.generation, args.vs_generation)
        policy = args.policy if args.policy != VIEWER_POLICY else first
        roster.expand(policy, len(roster.lineups.get(policy, [])) or config.num_snakes)
    elif args.generation is not None or args.vs_generation is not None:
        raise ValueError("--generation and --vs-generation need --run")
    else:
        policy_names(args.policy, config.num_snakes)
    return serve(
        host=args.host,
        port=args.port,
        config=config,
        seed=args.seed,
        policy=policy,
        replay_path=args.replay,
        open_browser=not args.no_browser,
        roster=roster,
        library=args.library or ["out"],
        runs_dir=args.runs_dir,
    )


def proposer_options(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    """Options for ``make_proposer``: only the opt-in ``llm`` proposer takes any."""
    if args.proposer != "llm":
        return {}
    from arena.rsi.llm import DEFAULT_MODEL

    return {
        "model": args.llm_model or DEFAULT_MODEL,
        "max_tokens": args.max_llm_tokens,
        "max_dollars": args.max_llm_dollars,
        "audit_path": run_dir / "llm_audit.jsonl",
    }


def add_llm_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group(
        "llm proposer (opt-in, needs the anthropic package and an API key; never the default)"
    )
    g.add_argument("--llm-model", help="model id (default: arena.rsi.llm.DEFAULT_MODEL)")
    g.add_argument("--max-llm-tokens", type=int, help="token cap; after it, hill climbing")
    g.add_argument("--max-llm-dollars", type=float, help="dollar cap; after it, hill climbing")


def cmd_rsi_meta(args: argparse.Namespace) -> int:
    from arena.rsi.meta import HillClimbTuning, meta_run

    out = args.out or f"runs/meta-{args.run_seed}"
    evaluator = HillClimbTuning(
        generations=args.inner_generations, workers=args.workers or os.cpu_count() or 1
    )
    run = meta_run(out, args.generations, args.run_seed, evaluator, pairs=args.pairs)

    def show(record: dict[str, object]) -> None:
        d = record["decision"]
        assert isinstance(d, dict)
        mark = "ACCEPT" if d["accept"] else "reject"
        print(f"gen {record['generation']:>3}  {mark}  {d['rationale']}", flush=True)

    result = run.run(on_generation=show)
    fmt = ", ".join(f"{k} {v:.3g}" for k, v in result.champion.params.items())
    print(
        f"\n{result.generations} generations, {result.accepted} accepted, stopped by "
        f"{result.stop_reason}.\nSettings kept: {fmt}"
    )
    if result.final is not None:
        f = result.final
        print(
            f"Final seeds ({f['n']} toy problems no proposer saw): mean true score "
            f"{f['mean_cand']:.3f} with these settings vs {f['mean_champ']:.3f} with the defaults, "
            f"difference {f['diff']:+.3f}, 95% CI [{f['ci'][0]:+.3f}, {f['ci'][1]:+.3f}]"
        )
    else:
        print("The defaults were never replaced, so there is nothing to compare.")
    print(f"Run directory: {out}")
    return 0


def cmd_rsi_demo(args: argparse.Namespace) -> int:
    from arena.rsi import Budget, PairedBootstrapRule, Run, RunConfig, make_proposer
    from arena.rsi.toys import PROBLEMS

    problem = PROBLEMS[args.problem](dim=args.dim, problem_seed=args.run_seed)
    out = Path(args.out or f"runs/{args.problem}-{args.proposer}-{args.run_seed}")
    config = RunConfig(
        run_seed=args.run_seed,
        problem=f"toy {args.problem} ({args.dim} dims)",
        patience=args.patience,
        budget=Budget(generations=args.generations),
    )
    proposer = make_proposer(args.proposer, **proposer_options(args, out))
    run = Run(out, problem.space, problem, proposer, PairedBootstrapRule(), config)

    def show(record: dict[str, object]) -> None:
        d = record["decision"]
        assert isinstance(d, dict)
        mark = "ACCEPT" if d["accept"] else "reject"
        print(f"gen {record['generation']:>3}  {mark}  {d['rationale']}")

    result = run.run(on_generation=show)
    best = problem.true_score(result.champion.params)
    start = problem.true_score(result.baseline.params)
    print(
        f"\n{result.generations} generations, {result.accepted} accepted, stopped by "
        f"{result.stop_reason}.\nTrue score (best possible 0): baseline {start:.3f}, "
        f"champion {best:.3f}.\nRun directory: {out} (report.md has the summary)"
    )
    return 0


def cmd_evolve(args: argparse.Namespace) -> int:
    from arena.evolution.run import PROFILES, Evolution
    from arena.rsi import make_proposer

    profile = PROFILES["quick" if args.quick else args.profile]
    if args.proposer is not None:
        profile = replace(profile, proposer=args.proposer)
    out = Path(args.runs_dir) / (args.run_id or f"{profile.name}-{args.run_seed}")
    args.proposer = profile.proposer

    def lineage_proposer(name: str) -> Proposer:
        return make_proposer(profile.proposer, **proposer_options(args, out / "lineages" / name))

    evo = Evolution(
        out,
        profile,
        args.generations,
        args.run_seed,
        args.workers,
        max_seconds=None if args.max_hours is None else args.max_hours * 3600,
        max_episodes=args.max_episodes,
        proposer=lineage_proposer,
        log=lambda m: print(m, flush=True),
    )
    started = time.monotonic()
    # The viewer's experiments screen reads this to tell a running run from a stopped one.
    pid_file = out.parent / f"{out.name}.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{os.getpid()}\n")
    try:
        result = evo.run()
    finally:
        with contextlib.suppress(OSError):
            if pid_file.read_text().strip() == str(os.getpid()):
                pid_file.unlink()
    print(
        f"\nStopped after generation {result.generations}: {result.stop_reason} "
        f"({time.monotonic() - started:.0f} s)."
    )
    for name, r in result.lineages.items():
        final = r.final
        vs = (
            f"final seeds vs generation 0: {final['diff']:+.3f} kills/1k ticks, "
            f"95% CI [{final['ci'][0]:+.3f}, {final['ci'][1]:+.3f}]"
            if final
            else "champion is still generation 0"
        )
        print(f"  {name}: {r.accepted} accepted; {vs}")
    label = (
        "" if profile.name == "default" else f" ({profile.name} profile, not the real experiment)"
    )
    print(f"Run directory: {out}{label}")
    return 0


def cmd_map_elites(args: argparse.Namespace) -> int:
    from arena.evolution.evaluator import Workers
    from arena.evolution.map_elites import heatmap_svg, snake_map_elites
    from arena.evolution.run import PROFILES
    from arena.rsi.map_elites import MapElitesConfig
    from arena.rsi.store import read_json

    settings = PROFILES[args.profile].settings
    out = Path(args.out or f"runs/map-elites-{args.snake}-{args.run_seed}")
    config = MapElitesConfig(
        run_seed=args.run_seed,
        batch=args.batch,
        dev_pairs=args.dev_pairs,
        holdout_pairs=args.holdout_pairs,
    )
    with Workers(args.workers) as workers:
        me = snake_map_elites(args.snake, out, settings, workers, config)
        while me.batches < args.batches and not (out / "STOP").exists():
            me.step()
            h = me.history[-1]
            print(
                f"batch {h['batch']:>3}: {h['cells']} cells, best {h['best']:.3f} kills/1k, "
                f"{h['changed']} changed",
                flush=True,
            )
        holdout = me.holdout(dict(me.start))
    (out / "map_elites.svg").write_text(heatmap_svg(read_json(me.path), holdout))
    base = holdout["baseline"]
    print(
        f"\nHoldout ({holdout['n']} seeds the search never saw): hand-set {args.snake} "
        f"{base['fitness']:.3f} kills/1k in cell {base['cell']}."
    )
    for e in sorted(holdout["elites"], key=lambda e: -e["holdout_fitness"])[:5]:
        print(
            f"  cell {e['cell']}: {e['holdout_fitness']:.3f} kills/1k, vs hand-set "
            f"{e['diff_vs_baseline']:+.3f} [{e['ci'][0]:+.3f}, {e['ci'][1]:+.3f}]"
        )
    print(f"Wrote {out / 'map_elites.json'}, holdout.json and map_elites.svg")
    return 0


def cmd_exploit(args: argparse.Namespace) -> int:
    from arena.evolution.exploit import train_exploiter

    ex = train_exploiter(
        args.run,
        args.snake,
        args.generations,
        target_generation=args.target_generation,
        workers=args.workers,
        league=not args.no_league,
    )
    r = ex.result
    print(
        f"{args.snake} exploiter vs the champions after generation {ex.target_generation}: "
        f"{r.accepted} accepted in {r.generations} generations ({r.stop_reason})."
    )
    if ex.gap is None:
        print("Exploit gap: none found (the exploiter never beat its starting champion).")
    else:
        lo, hi = ex.gap["ci"]
        print(
            f"Exploit gap on {ex.gap['n']} final seeds: {ex.gap['diff']:+.3f} kills/1k "
            f"[{lo:+.3f}, {hi:+.3f}] over the {args.snake} champion it started from."
        )
    if ex.registered:
        print(f"Registered in {Path(args.run) / 'league.json'}; it joins the halls of fame.")
    print(f"Wrote {ex.run.store.dir}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from arena.evolution.dashboard import write as write_dashboard
    from arena.evolution.report import write

    path = write(args.run, args.workers, rebuild=args.rebuild)
    page = write_dashboard(args.run)
    print(f"Wrote {path}, {path.with_name('progress.svg')} and {page}")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from arena.evolution.dashboard import write

    print(f"Wrote {write(args.run)}")
    return 0


def cmd_propose_code(args: argparse.Namespace) -> int:
    from arena.evolution.code_proposer import propose_code
    from arena.rsi.llm import DEFAULT_MODEL

    spent = 0.0
    for _ in range(args.count):
        if spent >= args.max_llm_dollars:
            print(f"Stopped: ${spent:.4f} spent, cap ${args.max_llm_dollars}")
            break
        p = propose_code(args.snake, args.out, args.run, model=args.llm_model or DEFAULT_MODEL)
        spent += p.dollars
        verdict = "static checks passed" if p.passed else "static checks FAILED"
        print(f"{p.path}: {verdict} (${p.dollars:.4f}); review {p.path / 'REVIEW.md'}")
    print("Nothing was applied or run. Promotion is manual; see REVIEW.md.")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from arena.storage.db import connect, index_paths, query

    if args.paths:
        db = connect(args.db)
        try:
            t = index_paths(db, args.paths)
        finally:
            db.close()
        print(
            f"Indexed {t['runs']} runs ({t['generations']} lineage generations) and "
            f"{t['matches']} matches from {t['match_files']} files into {args.db}"
        )
    if args.sql:
        cols, rows = query(args.db, args.sql)
        print("\t".join(cols))
        for row in rows:
            print("\t".join("" if v is None else str(v) for v in row))
    return 0


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
        "--workers",
        type=int,
        default=1,
        help="also measure total throughput over this many processes (as tournaments run)",
    )
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

    p = sub.add_parser(
        "rsi-demo",
        help="run the generic RSI loop on a toy problem (re-running the same --out resumes)",
    )
    p.add_argument("--problem", choices=["quadratic", "noise"], default="quadratic")
    p.add_argument("--proposer", default="gaussian_hill_climb")
    p.add_argument("--generations", type=int, default=60)
    p.add_argument("--dim", type=int, default=5)
    p.add_argument("--run-seed", type=int, default=0)
    p.add_argument("--patience", type=int, default=None)
    p.add_argument("--out", help="run directory (default runs/<problem>-<proposer>-<seed>)")
    add_llm_options(p)
    p.set_defaults(func=cmd_rsi_demo)

    p = sub.add_parser(
        "rsi-meta",
        help="improve the improver: tune GaussianHillClimb's settings on toy problems",
    )
    p.add_argument("--generations", type=int, default=15)
    p.add_argument("--inner-generations", type=int, default=30)
    p.add_argument("--pairs", type=int, default=12, help="dev and holdout toy problems")
    p.add_argument("--run-seed", type=int, default=0)
    p.add_argument("--workers", type=int, default=None, help="processes (default: all cores)")
    p.add_argument("--out", help="run directory (default runs/meta-<seed>)")
    p.set_defaults(func=cmd_rsi_meta)

    p = sub.add_parser(
        "evolve",
        help="phase 4: every personality tunes itself with the RSI loop (re-running resumes)",
    )
    p.add_argument("--generations", type=int, default=10)
    p.add_argument("--profile", choices=["default", "quick", "experiment"], default="default")
    p.add_argument("--quick", action="store_true", help="same as --profile quick")
    p.add_argument("--run-id", help="run directory name under --runs-dir")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--run-seed", type=int, default=0)
    p.add_argument("--workers", type=int, default=None, help="processes (default: all cores)")
    p.add_argument(
        "--max-hours",
        type=float,
        help="stop after the generation that passes this much run time, summed over resumes",
    )
    p.add_argument(
        "--max-episodes", type=int, help="stop a lineage once it has played this many episodes"
    )
    p.add_argument("--proposer", help="override the profile's proposer, e.g. llm (opt-in)")
    add_llm_options(p)
    p.set_defaults(func=cmd_evolve)

    p = sub.add_parser(
        "map-elites",
        help="step 5.2: best parameters per aggression x caution cell for one snake",
    )
    p.add_argument("snake", help="personality, e.g. hunter")
    p.add_argument("--batches", type=int, default=20, help="total batches (re-running resumes)")
    p.add_argument("--batch", type=int, default=16, help="parameter sets per batch")
    p.add_argument("--profile", choices=["default", "quick", "experiment"], default="experiment")
    p.add_argument("--dev-pairs", type=int, default=20, help="dev seeds every set plays")
    p.add_argument("--holdout-pairs", type=int, default=40, help="holdout seeds for the report")
    p.add_argument("--run-seed", type=int, default=0)
    p.add_argument("--workers", type=int, default=None, help="processes (default: all cores)")
    p.add_argument("--out", help="run directory (default runs/map-elites-<snake>-<seed>)")
    p.set_defaults(func=cmd_map_elites)

    p = sub.add_parser(
        "exploit",
        help="step 5.4: train an exploiter of an evolve run's champions; it joins the league",
    )
    p.add_argument("run", help="evolve run directory, e.g. runs/demo")
    p.add_argument("snake", help="personality the exploiter plays, e.g. hunter")
    p.add_argument("--generations", type=int, default=4, help="RSI generations to train")
    p.add_argument(
        "--target-generation", type=int, help="freeze champions after this generation (latest)"
    )
    p.add_argument("--no-league", action="store_true", help="do not register in league.json")
    p.add_argument("--workers", type=int, default=None, help="processes (default: all cores)")
    p.set_defaults(func=cmd_exploit)

    p = sub.add_parser("report", help="phase 4: write report.md and charts for an evolve run")
    p.add_argument("run", help="run directory, e.g. runs/demo")
    p.add_argument("--workers", type=int, default=None, help="processes (default: all cores)")
    p.add_argument("--rebuild", action="store_true", help="replay the report games again")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser(
        "dashboard", help="phase 4: write dashboard.html for an evolve run (cheap; no games)"
    )
    p.add_argument("run", help="run directory, e.g. runs/demo")
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser(
        "propose-code",
        help="opt-in: ask an LLM for a strategy-file patch, stored for review, never applied",
    )
    p.add_argument("snake", help="personality, e.g. hunter")
    p.add_argument("--run", help="evolve run whose dev results to show the model")
    p.add_argument("--out", default="proposals", help="where patches go (default proposals)")
    p.add_argument("--count", type=int, default=1, help="proposals to ask for (default 1)")
    p.add_argument("--llm-model", help="model id (default: arena.rsi.llm.DEFAULT_MODEL)")
    p.add_argument(
        "--max-llm-dollars", type=float, default=1.0, help="stop asking after this (default 1)"
    )
    p.set_defaults(func=cmd_propose_code)

    p = sub.add_parser("index", help="index runs and tournaments into SQLite; query it")
    p.add_argument("paths", nargs="*", help="folders to scan, e.g. out runs experiments")
    p.add_argument("--db", default="arena.db", help="SQLite file (default arena.db)")
    p.add_argument("--sql", help="run this read-only query after indexing")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("watch", help="open the browser viewer (live match or replay)")
    from arena.viz.server import VIEWER_DEFAULTS, VIEWER_POLICY

    add_game_options(p, VIEWER_DEFAULTS, VIEWER_POLICY)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--replay", help="open this replay file instead of a live match")
    p.add_argument(
        "--library",
        action="append",
        metavar="DIR",
        help="folder for the replay browser (repeatable; default: out); bookmarks go in the first",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    p.add_argument(
        "--runs-dir",
        default="runs",
        help="evolve runs the experiments screen lists and starts (default: runs)",
    )
    p.add_argument("--run", help="an evolve run directory: watch its archived champions")
    p.add_argument("--generation", type=int, help="with --run: the champions after this generation")
    p.add_argument(
        "--vs-generation", type=int, help="with --run: also seat each lineage's earlier version"
    )
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
