"""The human summary written to ``report.md`` at the end of a run."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from arena.rsi.types import ParamSpec

if TYPE_CHECKING:
    from arena.rsi.loop import RunResult
    from arena.rsi.store import RunStore


def _num(x: object) -> str:
    return f"{x:+.4g}" if isinstance(x, int | float) else "-"


def write_report(store: RunStore, result: RunResult, space: Sequence[ParamSpec]) -> None:
    config = store.config()
    ident = config["identity"]
    records = store.records()
    rule = ident["rule"]
    detail = (
        f" (min gain {rule['min_rel_gain']:.0%}, {rule['resamples']:,} bootstrap resamples)"
        if "min_rel_gain" in rule
        else ""
    )
    lines = [
        f"# RSI run: {ident['config']['problem']}",
        "",
        f"- proposer: `{ident['proposer']}`; rule: `{rule['rule']}`{detail}",
        f"- run seed {ident['config']['run_seed']}; framework v{config['framework_version']}, "
        f"code {config['code_hash']}",
        f"- generations: {result.generations}; accepted: {result.accepted}; "
        f"stopped by: {result.stop_reason}",
        f"- episodes used: {records[-1]['episodes'] if records else 0:,}",
        "",
        "## Final check (champion vs generation-0 baseline on the final seeds)",
        "",
    ]
    if result.final is None:
        lines.append("Nothing was accepted; the champion is still the baseline.")
    else:
        f = result.final
        lines.append(
            f"Mean score {f['mean_cand']:.4g} vs {f['mean_champ']:.4g} over {f['n']} seeds: "
            f"difference {f['diff']:+.4g}, 95% CI [{f['ci'][0]:+.4g}, {f['ci'][1]:+.4g}], "
            f"{f['failures']} failures."
        )
    lines += [
        "",
        "## Champion parameters",
        "",
        "| parameter | baseline | champion |",
        "|---|---|---|",
    ]
    for p in space:
        lines.append(
            f"| {p.name} | {result.baseline.params[p.name]:.4g} | "
            f"{result.champion.params[p.name]:.4g} |"
        )
    lines += [
        "",
        "## Decisions",
        "",
        "| gen | candidate | stage | dev diff | holdout diff | holdout CI | accepted | why |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for rec in records:
        d = rec["decision"]
        dev = d["stats"].get("dev", {})
        hold = d["stats"].get("holdout", {})
        ci = hold.get("ci")
        ci_text = f"[{ci[0]:+.3g}, {ci[1]:+.3g}]" if ci else "-"
        chosen = rec["chosen"] or "-"
        lines.append(
            f"| {rec['generation']} | {chosen[:8]} | {d['stage']} | {_num(dev.get('diff'))} | "
            f"{_num(hold.get('diff'))} | {ci_text} | {'yes' if d['accept'] else 'no'} | "
            f"{d['rationale'].replace('|', '/')} |"
        )
    store.write_report("\n".join(lines) + "\n")
