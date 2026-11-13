import json
import shutil
from pathlib import Path

import pytest

from arena.cli import main
from arena.engine import GameConfig
from arena.sim.tournament import run_matches, write_outputs
from arena.storage.db import connect, index_paths, query

BASELINE = Path(__file__).resolve().parents[2] / "experiments" / "2026-11-12-baseline"


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("data")
    config = GameConfig(width=16, height=16, max_ticks=3_000)
    write_outputs(root / "t", list(run_matches(["random_safe"] * 5, [7, 8, 9], config)))
    shutil.copytree(BASELINE, root / "runs" / "baseline")
    return root


def test_index_matches_and_runs_matches_the_files(data: Path, tmp_path: Path) -> None:
    db = connect(tmp_path / "a.db")
    totals = index_paths(db, [data])
    lines = [json.loads(x) for x in (data / "t" / "matches.jsonl").read_text().splitlines()]
    assert totals["matches"] == len(lines) == 3 and totals["runs"] == 1
    kills = sum(s["kills"] for rec in lines for s in rec["standings"])
    assert db.execute("SELECT SUM(kills) FROM match_participants").fetchone()[0] == kills
    matrix = sum(n for rec in lines for row in rec["kill_matrix"].values() for n in row.values())
    assert db.execute("SELECT COALESCE(SUM(count), 0) FROM kills").fetchone()[0] == matrix
    assert {r[0] for r in db.execute("SELECT DISTINCT policy FROM match_participants")} == {
        "random_safe"
    }

    gens = (BASELINE / "lineages" / "hunter" / "generations.jsonl").read_text().splitlines()
    n = db.execute(
        "SELECT COUNT(*) FROM promotion_decisions WHERE run_id='baseline' AND agent='hunter'"
    ).fetchone()[0]
    assert n == len(gens)
    first = json.loads(gens[0])
    row = db.execute(
        "SELECT dev_diff, accepted FROM candidate_evaluations "
        "WHERE run_id='baseline' AND agent='hunter' AND generation=1"
    ).fetchone()
    assert row[0] == pytest.approx(first["decision"]["stats"]["dev"]["diff"])
    assert row[1] == int(first["feedback"][0]["accepted"])
    assert db.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 5


def test_reindexing_is_idempotent(data: Path, tmp_path: Path) -> None:
    db = connect(tmp_path / "a.db")
    index_paths(db, [data])
    counts = [
        db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("matches", "match_participants", "kills", "generations", "candidate_evaluations")
    ]
    index_paths(db, [data])
    again = [
        db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("matches", "match_participants", "kills", "generations", "candidate_evaluations")
    ]
    assert counts == again and counts[0] == 3


def test_query_is_read_only(data: Path, tmp_path: Path) -> None:
    path = tmp_path / "a.db"
    index_paths(connect(path), [data])
    cols, rows = query(path, "SELECT COUNT(*) AS n FROM matches")
    assert cols == ["n"] and rows == [(3,)]
    with pytest.raises(Exception, match="readonly"):
        query(path, "DELETE FROM matches")


def test_cli_index_and_sql(data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "cli.db"
    assert main(["index", str(data), "--db", str(path)]) == 0
    assert "3 matches" in capsys.readouterr().out
    sql = "SELECT agent, COUNT(*) FROM promotion_decisions GROUP BY agent ORDER BY agent"
    assert main(["index", "--db", str(path), "--sql", sql]) == 0
    out = capsys.readouterr().out
    assert "hunter" in out and "trapper" in out
