"""Review-only code proposer (plan step 5.6, vision section 5).

The vision allows an optional coding LLM to propose changes to a snake's strategy
source, but only inside a hardened sandbox; without one, proposals must be review-only
with manual promotion. This project has no such sandbox, so this module:

- shows a language model one snake's strategy file, its current parameters and how its
  recent candidates did on *development* games (dev means and accept flags only, never
  holdout or final numbers, never seeds), and asks for a complete new version of the file;
- runs static checks on the answer (it parses, keeps the policy's name, imports only from
  an allowlist, avoids file, process and dynamic-code builtins) and records the result;
- writes the proposal as a unified diff plus an audit record under ``out/<snake>/<n>/``.

It never imports, executes or applies what the model wrote: the checks read the source
with ``ast`` only, and the diff is stored next to the repository, not in it. AST checks
are not a sandbox, so a passing proposal is a candidate for a person to read, not code to
trust. Promotion is manual: review ``patch.diff``, ``git apply`` it, run the tests and an
evolve or personality check, and commit it if it holds up. Calls are budgeted (dollar
cap) and only made when someone runs ``propose-code``; ``evolve`` never calls this.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.rsi.llm import DEFAULT_MODEL, DEFAULT_PRICES, Complete, anthropic_complete

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
MAX_SOURCE_BYTES = 40_000
ALLOWED_IMPORTS = (
    "__future__",
    "arena.agents",
    "arena.engine",
    "collections",
    "dataclasses",
    "functools",
    "itertools",
    "math",
    "typing",
)
BANNED_NAMES = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
    }
)
ALLOWED_DUNDERS = frozenset({"__init__", "__name__", "__class__"})

SYSTEM = (
    "You improve the strategy of one snake in a five-snake battle game played on a grid. "
    "You see its strategy file, its current parameters, the move features it can weigh, "
    "and how recent parameter changes did on development games. Propose ONE improved "
    "version of the whole file. Keep the class, its `name` and its public interface; "
    "import only from arena.agents, arena.engine and the standard modules already used; "
    "no file, network, process or randomness outside the policy's seeded RNG. Reply with "
    "one sentence of rationale, then the complete file in a single ```python block."
)


@dataclass(frozen=True)
class Proposal:
    """One stored proposal: where it is and whether its static checks passed."""

    path: Path
    passed: bool
    checks: dict[str, str]
    dollars: float


def strategy_path(snake: str) -> Path:
    path = AGENTS_DIR / f"{snake}.py"
    if not re.fullmatch(r"[a-z_]+", snake) or not path.is_file():
        raise ValueError(f"no strategy file for {snake!r} in arena/agents")
    return path


def dev_history(run_dir: str | Path | None, snake: str, recent: int = 12) -> list[dict[str, Any]]:
    """Recent generations of ``snake``'s lineage, reduced to what a proposer may see."""
    if run_dir is None:
        return []
    path = Path(run_dir) / "lineages" / snake / "generations.jsonl"
    if not path.is_file():
        raise ValueError(f"{path} not found; is --run an evolve run directory?")
    rows = []
    for line in path.read_text().splitlines()[-recent:]:
        rec = json.loads(line)
        decision = rec.get("decision", {})
        dev = decision.get("stats", {}).get("dev", {})
        chosen: dict[str, Any] = next(
            (
                f["candidate"]
                for f in rec.get("feedback", [])
                if f.get("candidate", {}).get("id") == rec.get("chosen")
            ),
            {},
        )
        rows.append(
            {
                "generation": rec.get("generation"),
                "change": chosen.get("note", ""),
                "dev_diff": dev.get("diff"),
                "dev_n": dev.get("n"),
                "accepted": bool(decision.get("accept")),
            }
        )
    return rows


def build_prompt(
    snake: str, source: str, params: Mapping[str, Any], history: Sequence[Mapping[str, Any]]
) -> str:
    from arena.agents.features import FEATURES

    lines = [
        f"Snake: {snake}. Objective: kills (ties broken by survival); see the phase 2 spec.",
        f"Strategy file arena/agents/{snake}.py:",
        "```python",
        source.rstrip(),
        "```",
        "Current parameters: " + json.dumps(dict(params), sort_keys=True),
        "Move features available as weights (w_<feature>): " + ", ".join(sorted(FEATURES)),
    ]
    if history:
        lines.append("Recent parameter changes (dev games, diff > 0 means the change won):")
        for h in history:
            verdict = "accepted" if h["accepted"] else "rejected"
            lines.append(
                f"- gen {h['generation']}: {h['change']} dev diff {h['dev_diff']} ({verdict})"
            )
    lines.append("Return the complete new file.")
    return "\n".join(lines)


def extract_source(text: str) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
    if not blocks:
        raise ValueError("the reply has no ```python block")
    longest: str = max(blocks, key=len)
    return longest.rstrip() + "\n"


def _module_allowed(module: str) -> bool:
    return any(module == a or module.startswith(a + ".") for a in ALLOWED_IMPORTS)


def static_checks(source: str, snake: str) -> dict[str, str]:
    """Check a proposed file without running it; each value is "ok" or the problem."""
    checks = {"size": "ok", "parses": "ok", "imports": "ok", "names": "ok", "interface": "ok"}
    if len(source.encode()) > MAX_SOURCE_BYTES:
        checks["size"] = f"over {MAX_SOURCE_BYTES} bytes"
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return (
            checks
            | {k: "not checked" for k in ("imports", "names", "interface")}
            | {"parses": f"syntax error line {exc.lineno}: {exc.msg}"}
        )
    bad_imports, bad_names = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad_imports += [a.name for a in node.names if not _module_allowed(a.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.level or not _module_allowed(node.module or ""):
                bad_imports.append("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            bad_names.append(node.id)
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("__") and attr.endswith("__") and attr not in ALLOWED_DUNDERS:
                bad_names.append(attr)
    if bad_imports:
        checks["imports"] = "not allowed: " + ", ".join(sorted(set(bad_imports)))
    if bad_names:
        checks["names"] = "not allowed: " + ", ".join(sorted(set(bad_names)))
    named = any(
        isinstance(cls, ast.ClassDef)
        and any(
            isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "name" for t in stmt.targets)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value == snake
            for stmt in cls.body
        )
        for cls in tree.body
    )
    if not named:
        checks["interface"] = f'no top-level class with name = "{snake}"'
    return checks


def _next_dir(base: Path) -> Path:
    taken = [int(p.name) for p in base.glob("[0-9][0-9][0-9]") if p.is_dir()]
    path = base / f"{max(taken, default=0) + 1:03d}"
    path.mkdir(parents=True)
    return path


REVIEW = """# Proposed change to arena/agents/{snake}.py (review only)

Static checks: {verdict}
{checks}

Rationale from the model: {rationale}

Nothing here has been run. Static checks are not a sandbox: read the diff in full first.
To try it:

    git apply {patch}
    uv run pytest && uv run mypy
    uv run python -m arena.cli evolve --quick --generations 3 --run-id try-{snake}

Commit it only if the tests pass and the snake measurably holds up; otherwise
`git checkout arena/agents/{snake}.py`.
"""


def propose_code(
    snake: str,
    out: str | Path,
    run_dir: str | Path | None = None,
    complete: Complete | None = None,
    model: str = DEFAULT_MODEL,
    prices: tuple[float, float] = DEFAULT_PRICES,
) -> Proposal:
    """Ask once for a new strategy file and store it as a reviewable patch."""
    from arena.agents.params import load_params
    from arena.agents.registry import make_policy

    path = strategy_path(snake)
    source = path.read_text()
    policy: Any = make_policy(snake)
    params = load_params(snake, policy.param_space).params
    prompt = build_prompt(snake, source, params, dev_history(run_dir, snake))
    reply = (complete or anthropic_complete(model, max_tokens=8192))(SYSTEM, prompt)
    dollars = (reply.input_tokens * prices[0] + reply.output_tokens * prices[1]) / 1e6
    target = _next_dir(Path(out) / snake)
    audit: dict[str, Any] = {
        "snake": snake,
        "model": model,
        "prompt": prompt,
        "reply": reply.text,
        "input_tokens": reply.input_tokens,
        "output_tokens": reply.output_tokens,
        "dollars": round(dollars, 6),
        "refused": reply.refused,
    }
    try:
        if reply.refused:
            raise ValueError("the model declined")
        proposed = extract_source(reply.text)
    except ValueError as exc:
        checks = {"reply": str(exc)}
        (target / "audit.json").write_text(json.dumps(audit | {"checks": checks}, indent=2))
        return Proposal(target, False, checks, dollars)
    checks = static_checks(proposed, snake)
    passed = all(v == "ok" for v in checks.values())
    rel = f"arena/agents/{snake}.py"
    diff = "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            f"a/{rel}",
            f"b/{rel}",
        )
    )
    (target / "patch.diff").write_text(diff)
    (target / "audit.json").write_text(json.dumps(audit | {"checks": checks}, indent=2))
    rationale = reply.text.split("```", 1)[0].strip() or "(none given)"
    (target / "REVIEW.md").write_text(
        REVIEW.format(
            snake=snake,
            verdict="passed" if passed else "FAILED, do not apply",
            checks="\n".join(f"- {k}: {v}" for k, v in checks.items()),
            rationale=rationale,
            patch=target / "patch.diff",
        )
    )
    return Proposal(target, passed, checks, dollars)
