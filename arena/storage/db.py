"""SQLite index over the files tournaments and evolve runs write (vision §4, plan step 5.7).

The JSON and JSONL files stay the record: runs write them atomically and append-only,
and nothing here changes them. This module reads them into one SQLite database so
questions across many runs and matches become one SQL query. Re-indexing is idempotent:
each source's rows are replaced in one transaction, so an index can be refreshed while a
run is still writing.

Tables follow the vision's list:

- ``runs``, ``agents`` (one lineage per run), ``policy_versions`` (accepted parameter
  sets), ``generations``, ``candidate_evaluations`` (dev-screen results),
  ``promotion_decisions`` (accept / reject with holdout numbers when it got that far);
- ``matches``, ``match_participants`` (standings) and ``kills`` (killer, victim, count).

``kills`` holds the per-match kill matrix rather than one row per kill event, because
``matches.jsonl`` records the matrix; the per-tick events live in replay files.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, path TEXT, profile TEXT, proposer TEXT, run_seed INTEGER,
    code_hash TEXT, generation INTEGER
);
CREATE TABLE IF NOT EXISTS agents (
    run_id TEXT, agent TEXT, version INTEGER, accepted INTEGER, stop_reason TEXT,
    PRIMARY KEY (run_id, agent)
);
CREATE TABLE IF NOT EXISTS policy_versions (
    run_id TEXT, agent TEXT, version INTEGER, params TEXT,
    PRIMARY KEY (run_id, agent, version)
);
CREATE TABLE IF NOT EXISTS generations (
    run_id TEXT, agent TEXT, generation INTEGER, episodes INTEGER, chosen TEXT,
    champion_before TEXT, champion_after TEXT,
    PRIMARY KEY (run_id, agent, generation)
);
CREATE TABLE IF NOT EXISTS candidate_evaluations (
    run_id TEXT, agent TEXT, generation INTEGER, candidate_id TEXT, proposer TEXT,
    note TEXT, stage TEXT, accepted INTEGER, dev_n INTEGER, dev_mean_cand REAL,
    dev_mean_champ REAL, dev_diff REAL, params TEXT
);
CREATE TABLE IF NOT EXISTS promotion_decisions (
    run_id TEXT, agent TEXT, generation INTEGER, accept INTEGER, stage TEXT,
    rationale TEXT, dev_diff REAL, holdout_n INTEGER, holdout_diff REAL,
    holdout_ci_low REAL, holdout_ci_high REAL, holdout_rel_gain REAL,
    PRIMARY KEY (run_id, agent, generation)
);
CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY, source TEXT, seed INTEGER, ticks INTEGER,
    end_reason TEXT, winner TEXT, width INTEGER, height INTEGER, policies TEXT
);
CREATE TABLE IF NOT EXISTS match_participants (
    match_id TEXT, snake TEXT, policy TEXT, rank INTEGER, kills INTEGER, deaths INTEGER,
    alive_ticks INTEGER, PRIMARY KEY (match_id, snake)
);
CREATE TABLE IF NOT EXISTS kills (
    match_id TEXT, killer TEXT, victim TEXT, count INTEGER,
    PRIMARY KEY (match_id, killer, victim)
);
CREATE INDEX IF NOT EXISTS candidate_run ON candidate_evaluations (run_id, agent, generation);
CREATE INDEX IF NOT EXISTS participant_policy ON match_participants (policy);
"""

RUN_TABLES = (
    "runs",
    "agents",
    "policy_versions",
    "generations",
    "candidate_evaluations",
    "promotion_decisions",
)


def connect(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db


def _jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open() as f:
        for line in f:
            try:
                yield json.loads(line)
            except ValueError:
                continue  # a line a live run is writing right now


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def index_run(db: sqlite3.Connection, run: Path) -> int:
    """Replace one evolve run's rows; returns the number of generation rows."""
    meta = _json(run / "evolution.json")
    if not isinstance(meta, dict) or "identity" not in meta:
        raise ValueError(f"{run} is not an evolve run (no evolution.json)")
    identity = meta["identity"]
    run_id = run.name
    final = _json(run / "final.json") or {}
    rows = 0
    with db:
        for table in RUN_TABLES:
            db.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))
        db.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                str(run),
                identity["profile"]["name"],
                identity["profile"].get("proposer"),
                identity.get("run_seed"),
                meta.get("code_hash"),
                final.get("generation"),
            ),
        )
        for agent in identity["lineages"]:
            gens = run / "lineages" / agent / "generations.jsonl"
            accepted = 0
            for rec in _jsonl(gens) if gens.is_file() else iter(()):
                rows += 1
                accepted += _index_generation(db, run_id, agent, rec)
            lin = final.get("lineages", {}).get(agent, {})
            db.execute(
                "INSERT INTO agents VALUES (?, ?, ?, ?, ?)",
                (run_id, agent, 1 + accepted, accepted, lin.get("stop_reason")),
            )
            for path in sorted((run / "params" / agent).glob("v*.json")):
                pset = _json(path)
                if isinstance(pset, dict):
                    db.execute(
                        "INSERT OR REPLACE INTO policy_versions VALUES (?, ?, ?, ?)",
                        (run_id, agent, pset["version"], json.dumps(pset["params"])),
                    )
    return rows


def _index_generation(db: sqlite3.Connection, run_id: str, agent: str, rec: dict[str, Any]) -> int:
    gen = rec["generation"]
    decision = rec["decision"]
    stats = decision.get("stats", {})
    dev, holdout = stats.get("dev") or {}, stats.get("holdout") or {}
    ci = holdout.get("ci") or [None, None]
    db.execute(
        "INSERT OR REPLACE INTO generations VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            agent,
            gen,
            rec.get("episodes"),
            rec.get("chosen"),
            rec.get("champion_before"),
            rec.get("champion_after"),
        ),
    )
    db.execute(
        "INSERT OR REPLACE INTO promotion_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            agent,
            gen,
            int(bool(decision.get("accept"))),
            decision.get("stage"),
            decision.get("rationale"),
            dev.get("diff"),
            holdout.get("n"),
            holdout.get("diff"),
            ci[0],
            ci[1],
            holdout.get("rel_gain"),
        ),
    )
    for fb in rec.get("feedback", []):
        cand = fb.get("candidate", {})
        fdev = fb.get("dev") or {}
        cand_scores, champ_scores = fdev.get("score_cand") or [], fdev.get("score_champ") or []
        n = len(cand_scores)
        mean_c = sum(cand_scores) / n if n else None
        mean_h = sum(champ_scores) / n if n else None
        db.execute(
            "INSERT INTO candidate_evaluations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                agent,
                gen,
                cand.get("id"),
                cand.get("proposer"),
                cand.get("note"),
                fb.get("stage"),
                int(bool(fb.get("accepted"))),
                n,
                mean_c,
                mean_h,
                None if mean_c is None or mean_h is None else mean_c - mean_h,
                json.dumps(cand.get("params", {}), sort_keys=True),
            ),
        )
    return int(bool(decision.get("accept")))


def index_matches(db: sqlite3.Connection, path: Path, source: str | None = None) -> int:
    """Replace the rows of one ``matches.jsonl``; returns the number of matches."""
    source = source or str(path.parent)
    count = 0
    with db:
        old = [r[0] for r in db.execute("SELECT match_id FROM matches WHERE source = ?", (source,))]
        for table in ("match_participants", "kills", "matches"):
            db.executemany(f"DELETE FROM {table} WHERE match_id = ?", ((m,) for m in old))
        for i, rec in enumerate(_jsonl(path)):
            match_id = f"{source}#{i}"
            policies = rec["policies"]
            config = rec.get("config", {})
            db.execute(
                "INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    match_id,
                    source,
                    rec["seed"],
                    rec["ticks"],
                    rec["end_reason"],
                    rec.get("winner"),
                    config.get("width"),
                    config.get("height"),
                    json.dumps(policies),
                ),
            )
            for s in rec.get("standings", []):
                seat = int(s["snake"][1:])  # snake ids are s0, s1, ... in seat order
                db.execute(
                    "INSERT INTO match_participants VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        match_id,
                        s["snake"],
                        policies[seat] if seat < len(policies) else None,
                        s["rank"],
                        s["kills"],
                        s["deaths"],
                        s["alive_ticks"],
                    ),
                )
            db.executemany(
                "INSERT INTO kills VALUES (?, ?, ?, ?)",
                (
                    (match_id, killer, victim, n)
                    for killer, row in rec.get("kill_matrix", {}).items()
                    for victim, n in row.items()
                    if n
                ),
            )
            count += 1
    return count


def index_paths(db: sqlite3.Connection, paths: Sequence[str | Path]) -> dict[str, int]:
    """Index every evolve run and ``matches.jsonl`` found under ``paths``."""
    totals = {"runs": 0, "generations": 0, "match_files": 0, "matches": 0}
    for root in map(Path, paths):
        for meta in sorted(root.rglob("evolution.json")):
            totals["generations"] += index_run(db, meta.parent)
            totals["runs"] += 1
        for matches in sorted(root.rglob("matches.jsonl")):
            totals["matches"] += index_matches(db, matches)
            totals["match_files"] += 1
    return totals


def query(path: str | Path, sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Run ``sql`` on a read-only connection; returns column names and rows."""
    db = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        cur = db.execute(sql)
        return [d[0] for d in cur.description or ()], cur.fetchall()
    finally:
        db.close()
