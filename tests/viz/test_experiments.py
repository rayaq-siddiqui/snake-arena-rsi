import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from arena.cli import build_parser
from arena.evolution import report
from arena.evolution.evaluator import EvalSettings
from arena.evolution.run import Evolution, Profile
from arena.viz.experiments import Experiments
from arena.viz.server import make_server

TINY = Profile(
    "tiny",
    EvalSettings(12, 12, 80),
    dev_pairs=3,
    holdout_pairs=3,
    holdout_blocks=2,
    final_pairs=3,
    dev_pool=40,
    patience=3,
    resamples=200,
)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    runs = tmp_path_factory.mktemp("runs")
    Evolution(runs / "done", TINY, 2, workers=1, lineages=("hunter", "predictor")).run()
    report.build(runs / "done", workers=1)
    return runs


@pytest.fixture
def runs(built: Path, tmp_path: Path) -> Path:
    shutil.copytree(built, tmp_path / "runs")
    return tmp_path / "runs"


class FakeLaunch:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, argv: Sequence[str], log: Path) -> int:
        self.calls.append((list(argv), log))
        return 999_999_999  # no such process, so the run reads as not running


def test_runs_and_detail_match_the_run_files(runs: Path) -> None:
    exp = Experiments(runs)
    [row] = exp.runs()
    final = json.loads((runs / "done" / "final.json").read_text())
    assert row["id"] == "done" and row["profile"] == "tiny"
    assert row["status"] == "finished" and row["generation"] == 2
    assert row["accepted"] == sum(v["accepted"] for v in final["lineages"].values())
    detail = exp.detail("done")
    assert list(detail["lineages"]) == ["hunter", "predictor"]
    for name, lin in detail["lineages"].items():
        records = (runs / "done" / "lineages" / name / "generations.jsonl").read_text()
        assert len(lin["timeline"]) == len(records.splitlines()) == 2
        assert lin["accepted"] == final["lineages"][name]["accepted"]
        assert all(r["stage"] for r in lin["timeline"])
    assert detail["matrix"]["snakes"] and set(detail["progress"]) == {"hunter", "predictor"}
    assert exp.dashboard("done").startswith(b"<!doctype html>")


def test_start_builds_an_evolve_command_and_pid_file(runs: Path) -> None:
    (runs / "new").mkdir()
    (runs / "new" / "STOP").touch()
    launch = FakeLaunch()
    exp = Experiments(runs, launch=launch)
    out = exp.start({"run_id": "new", "profile": "quick", "generations": 4, "workers": 2})
    [(argv, log)] = launch.calls
    assert argv[:3] == [sys.executable, "-m", "arena.cli"] and out["pid"] == 999_999_999
    assert log == runs / "new.log"
    assert (runs / "new.pid").read_text().strip() == "999999999"
    args = build_parser().parse_args(argv[3:])
    assert (args.run_id, args.profile, args.generations, args.workers) == ("new", "quick", 4, 2)
    assert Path(args.runs_dir) == runs
    assert not (runs / "new" / "STOP").exists()


def test_start_validates_the_request(runs: Path) -> None:
    exp = Experiments(runs, launch=FakeLaunch())
    for bad in (
        {"run_id": "../escape"},
        {"run_id": "x", "profile": "huge"},
        {"run_id": "x", "generations": 0},
        {"run_id": "x", "max_hours": -1},
        {"run_id": "x", "workers": 1000},
        {"run_id": "done", "profile": "quick"},  # a resume must keep its profile
    ):
        with pytest.raises(ValueError):
            exp.start(bad)


def test_a_running_run_cannot_be_started_twice(runs: Path) -> None:
    (runs / "done.pid").write_text(f"{os.getpid()}\n")
    exp = Experiments(runs, launch=FakeLaunch())
    assert exp.status("done") == "running"
    with pytest.raises(ValueError, match="already running"):
        exp.start({"run_id": "done", "profile": "quick"})
    exp.stop("done")
    assert (runs / "done" / "STOP").exists() and exp.status("done") == "stopping"
    with pytest.raises(LookupError):
        exp.stop("missing")


@pytest.fixture
def base_url(runs: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setattr(
        "arena.viz.server.Experiments", lambda d: Experiments(d, launch=FakeLaunch())
    )
    server = make_server(port=0, runs_dir=runs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(url: str) -> Any:
    with urllib.request.urlopen(url) as r:
        return r.read()


def post(url: str, body: dict[str, Any], content_type: str = "application/json") -> Any:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": content_type}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_server_routes(base_url: str, runs: Path) -> None:
    assert b"start-form" in get(base_url + "/experiments")
    assert json.loads(get(base_url + "/api/info"))["experiments"] is True
    assert [r["id"] for r in json.loads(get(base_url + "/api/runs"))] == ["done"]
    assert json.loads(get(base_url + "/api/runs/done"))["status"] == "finished"
    assert get(base_url + "/api/runs/done/dashboard").startswith(b"<!doctype html>")
    started = post(base_url + "/api/runs", {"run_id": "fresh", "profile": "quick"})
    assert started["id"] == "fresh" and (runs / "fresh.pid").exists()
    assert post(base_url + "/api/runs/done/stop", {})["id"] == "done"
    assert (runs / "done" / "STOP").exists()
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(base_url + "/api/runs/nope")
    assert exc.value.code == 410


def test_posts_must_be_json(base_url: str, runs: Path) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base_url + "/api/runs/done/stop", {}, content_type="text/plain")
    assert exc.value.code == 415
    assert not (runs / "done" / "STOP").exists()
