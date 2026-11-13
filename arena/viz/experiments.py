"""The viewer's experiments screen (vision section 7): see evolve runs, start and stop them.

It only reads the files an ``evolve`` run writes (``evolution.json``, each lineage's
``generations.jsonl``, ``timing.jsonl``, ``final.json``, ``report.json``) and starts or
stops runs the same way a person would on the command line:

- Start (or resume) launches ``python -m arena.cli evolve`` as a separate process in its
  own session, logging to ``<runs>/<id>.log`` and writing its pid to ``<runs>/<id>.pid``.
  It keeps running if the viewer is closed.
- Stop creates the run's ``STOP`` file, so the run ends cleanly after the current
  generation, exactly like creating the file by hand. Start removes it again.

So the screen can't change how a run is evaluated: the run identity check in
``Evolution`` still refuses a resume with different settings, and the browser can't
choose the opt-in LLM proposer, so it can never spend money.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

PROFILES = ("quick", "experiment", "default")
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
LOG_TAIL = 40

Launch = Callable[[Sequence[str], Path], int]
"""``launch(argv, log_path)`` starts a process and returns its pid."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a line being written right now
    return out


def _timeline_row(rec: dict[str, Any]) -> dict[str, Any]:
    decision = rec.get("decision", {})
    stats = decision.get("stats", {})
    chosen: dict[str, Any] = next(
        (
            f["candidate"]
            for f in rec.get("feedback", [])
            if f.get("candidate", {}).get("id") == rec.get("chosen")
        ),
        {},
    )
    holdout = stats.get("holdout") or {}
    dev = stats.get("dev") or {}
    return {
        "generation": rec.get("generation"),
        "accept": bool(decision.get("accept")),
        "stage": decision.get("stage"),
        "rationale": decision.get("rationale", ""),
        "proposer": chosen.get("proposer"),
        "change": chosen.get("note", ""),
        "dev_diff": dev.get("diff"),
        "holdout_diff": holdout.get("diff"),
        "holdout_ci": holdout.get("ci"),
        "episodes": rec.get("episodes"),
    }


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def popen_launch(argv: Sequence[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        proc = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _children[proc.pid] = proc
    return proc.pid


_children: dict[int, subprocess.Popen[bytes]] = {}


def _running(pid: int) -> bool:
    child = _children.get(pid)
    if child is not None:
        return child.poll() is None  # also reaps a finished child
    return pid_alive(pid)


class Experiments:
    """Evolve runs under one folder: list, inspect, start, stop."""

    def __init__(self, runs_dir: str | Path, launch: Launch = popen_launch) -> None:
        self.dir = Path(runs_dir)
        self.launch = launch
        self.lock = threading.Lock()

    def _run_dir(self, run_id: str) -> Path:
        if not RUN_ID.fullmatch(run_id):
            raise ValueError("a run id is letters, digits, '.', '_' or '-' (64 at most)")
        return self.dir / run_id

    def _pid(self, run_id: str) -> int | None:
        try:
            pid = int((self.dir / f"{run_id}.pid").read_text().strip())
        except (OSError, ValueError):
            return None
        return pid if _running(pid) else None

    def status(self, run_id: str) -> str:
        run = self.dir / run_id
        running = self._pid(run_id) is not None
        if running:
            return "stopping" if (run / "STOP").exists() else "running"
        if (run / "final.json").exists():
            return "finished"
        return "idle" if (run / "evolution.json").exists() else "starting"

    def runs(self) -> list[dict[str, Any]]:
        if not self.dir.is_dir():
            return []
        out = []
        for run in sorted(self.dir.iterdir()):
            meta = _read_json(run / "evolution.json") if run.is_dir() else None
            if not isinstance(meta, dict) or "identity" not in meta:
                continue
            identity = meta["identity"]
            final = _read_json(run / "final.json") or {}
            timing = _jsonl(run / "timing.jsonl")
            out.append(
                {
                    "id": run.name,
                    "profile": identity["profile"]["name"],
                    "proposer": identity["profile"].get("proposer"),
                    "lineages": identity["lineages"],
                    "generation": max((t["generation"] for t in timing), default=0),
                    "seconds": round(sum(float(t["seconds"]) for t in timing), 1),
                    "accepted": sum(
                        int(v.get("accepted", 0)) for v in final.get("lineages", {}).values()
                    )
                    if final
                    else None,
                    "status": self.status(run.name),
                    "stop_reason": final.get("stop_reason"),
                    "report": (run / "report.json").exists(),
                }
            )
        return out

    def detail(self, run_id: str) -> dict[str, Any]:
        run = self._run_dir(run_id)
        meta = _read_json(run / "evolution.json")
        if not isinstance(meta, dict):
            raise LookupError(f"no evolve run named {run_id!r}")
        identity = meta["identity"]
        lineages = {}
        for name in identity["lineages"]:
            rows = [_timeline_row(r) for r in _jsonl(run / "lineages" / name / "generations.jsonl")]
            lineages[name] = {
                "timeline": rows,
                "accepted": sum(r["accept"] for r in rows),
                "version": 1 + sum(r["accept"] for r in rows),
            }
        report = _read_json(run / "report.json")
        progress = None
        if isinstance(report, dict):
            progress = {
                name: [
                    {k: p.get(k) for k in ("version", "generation", "mean", "ci")}
                    for p in lin.get("progress", [])
                ]
                for name, lin in report.get("lineages", {}).items()
            }
        log = self.dir / f"{run_id}.log"
        try:
            tail = log.read_text(errors="replace").splitlines()[-LOG_TAIL:]
        except OSError:
            tail = []
        final = _read_json(run / "final.json") or {}
        return {
            "id": run_id,
            "status": self.status(run_id),
            "identity": identity,
            "stop_file": (run / "STOP").exists(),
            "stop_reason": final.get("stop_reason"),
            "lineages": lineages,
            "timing": _jsonl(run / "timing.jsonl"),
            "progress": progress,
            "matrix": report.get("matrix") if isinstance(report, dict) else None,
            "dashboard": (run / "dashboard.html").exists(),
            "log": tail,
        }

    def command(self, body: dict[str, Any]) -> tuple[str, list[str]]:
        """Check a start request and build its ``evolve`` command line."""
        run_id = str(body.get("run_id", "")).strip()
        self._run_dir(run_id)
        profile = str(body.get("profile", "quick"))
        if profile not in PROFILES:
            raise ValueError(f"profile must be one of {', '.join(PROFILES)}")
        generations = int(body.get("generations", 3))
        if not 1 <= generations <= 10_000:
            raise ValueError("generations must be between 1 and 10000")
        argv = [
            sys.executable,
            "-m",
            "arena.cli",
            "evolve",
            "--runs-dir",
            str(self.dir),
            "--run-id",
            run_id,
            "--profile",
            profile,
            "--generations",
            str(generations),
        ]
        if body.get("max_hours") not in (None, ""):
            hours = float(body["max_hours"])
            if not hours > 0:
                raise ValueError("max hours must be positive")
            argv += ["--max-hours", str(hours)]
        if body.get("workers") not in (None, ""):
            workers = int(body["workers"])
            if not 1 <= workers <= 256:
                raise ValueError("workers must be between 1 and 256")
            argv += ["--workers", str(workers)]
        return run_id, argv

    def start(self, body: dict[str, Any]) -> dict[str, Any]:
        run_id, argv = self.command(body)
        with self.lock:
            if self._pid(run_id) is not None:
                raise ValueError(f"{run_id} is already running")
            run = self.dir / run_id
            stored = _read_json(run / "evolution.json")
            if isinstance(stored, dict):
                had = stored["identity"]["profile"]["name"]
                if had != argv[argv.index("--profile") + 1]:
                    raise ValueError(f"{run_id} was started with the {had} profile")
            (run / "STOP").unlink(missing_ok=True)
            pid = self.launch(argv, self.dir / f"{run_id}.log")
            (self.dir / f"{run_id}.pid").write_text(f"{pid}\n")
        return {"id": run_id, "pid": pid, "argv": argv[1:]}

    def stop(self, run_id: str) -> dict[str, Any]:
        run = self._run_dir(run_id)
        if not (run / "evolution.json").exists() and self._pid(run_id) is None:
            raise LookupError(f"no evolve run named {run_id!r}")
        run.mkdir(parents=True, exist_ok=True)
        (run / "STOP").touch()
        return {"id": run_id, "status": self.status(run_id)}

    def dashboard(self, run_id: str) -> bytes:
        path = self._run_dir(run_id) / "dashboard.html"
        if not path.is_file():
            raise LookupError(f"{run_id} has no dashboard yet")
        return path.read_bytes()
