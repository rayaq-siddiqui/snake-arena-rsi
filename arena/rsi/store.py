"""Run directory layout and the immutable archive (phase 3 spec, sections 7 and 9).

```
<run_dir>/
  config.json            run config + framework version + code hash
  seeds.json             dev / holdout / final pools
  generations.jsonl      one record per generation
  archive/<cand-id>.json immutable accepted candidates (and the generation-0 baseline)
  champion.json          pointer to the current champion
  checkpoint.json        what a resumed run needs (proposer state, counters)
  report.md              human summary written at the end
```

Every file is written atomically (temp file + rename). A generation counts as committed
once ``checkpoint.json`` names it; on resume, any later lines in ``generations.jsonl``
(from a run killed mid-write) are dropped.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import numpy as np

from arena.rsi.types import Candidate

FRAMEWORK_VERSION = 1
OpponentMode = Literal["latest", "baseline", "uniform", "milestones"]


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_json(path: Path, data: Any) -> None:
    write_atomic(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def code_hash(root: Path | None = None, patterns: tuple[str, ...] = ("*.py",)) -> str:
    """Hash of the files under ``root`` matching ``patterns`` (default: the framework's own
    source), recorded with every run."""
    root = root or Path(__file__).parent
    h = hashlib.sha256()
    files = sorted({f for pat in patterns for f in root.rglob(pat) if "__pycache__" not in f.parts})
    for f in files:
        h.update(f.relative_to(root).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


class Archive:
    """The hall of fame: the baseline plus every accepted candidate, in order. Never edited."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.members: list[Candidate] = []

    def add(self, candidate: Candidate) -> None:
        path = self.directory / f"{candidate.id}.json"
        data = candidate.to_dict()
        if path.exists():
            if read_json(path) != data:
                raise RuntimeError(f"archive entry {candidate.id} exists with different content")
        else:
            write_json(path, data)
        self.members.append(candidate)

    def load(self, ids: Sequence[str]) -> None:
        self.members = [Candidate.from_dict(read_json(self.directory / f"{i}.json")) for i in ids]

    def opponents(
        self, mode: OpponentMode, n: int = 1, rng: np.random.Generator | None = None, every: int = 5
    ) -> list[Candidate]:
        """Opponents drawn from the archive, so a problem can play past champions too.

        ``latest``: the newest n. ``baseline``: generation 0. ``uniform``: n drawn uniformly
        (with ``rng``). ``milestones``: every ``every``-th champion, newest first, up to n.
        """
        m = self.members
        if not m:
            return []
        if mode == "latest":
            return m[-n:][::-1]
        if mode == "baseline":
            return [m[0]]
        if mode == "uniform":
            if rng is None:
                raise ValueError("uniform opponents need an rng")
            return [m[int(i)] for i in rng.integers(0, len(m), size=n)]
        if mode == "milestones":
            return m[::every][::-1][:n]
        raise ValueError(f"unknown opponent mode {mode!r}")


class RunStore:
    def __init__(self, run_dir: Path) -> None:
        self.dir = Path(run_dir)
        self.archive = Archive(self.dir / "archive")

    @property
    def generations_path(self) -> Path:
        return self.dir / "generations.jsonl"

    def exists(self) -> bool:
        return (self.dir / "config.json").exists()

    def create(self, config: dict[str, Any], seeds: dict[str, Any]) -> None:
        (self.dir / "archive").mkdir(parents=True, exist_ok=True)
        write_json(self.dir / "seeds.json", seeds)
        write_atomic(self.generations_path, "")
        write_json(
            self.dir / "config.json",
            {**config, "framework_version": FRAMEWORK_VERSION, "code_hash": code_hash()},
        )

    def config(self) -> dict[str, Any]:
        data: dict[str, Any] = read_json(self.dir / "config.json")
        return data

    def seeds(self) -> dict[str, Any]:
        data: dict[str, Any] = read_json(self.dir / "seeds.json")
        return data

    def records(self) -> list[dict[str, Any]]:
        lines = self.generations_path.read_text().splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def append_record(self, record: dict[str, Any]) -> None:
        with open(self.generations_path, "a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def truncate_records(self, keep: int) -> None:
        records = self.records()
        if len(records) > keep:
            text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in records[:keep])
            write_atomic(self.generations_path, text)

    def checkpoint(self) -> dict[str, Any] | None:
        path = self.dir / "checkpoint.json"
        if not path.exists():
            return None
        data: dict[str, Any] = read_json(path)
        return data

    def save_checkpoint(self, state: dict[str, Any], champion: Candidate) -> None:
        write_json(self.dir / "champion.json", {"id": champion.id, "params": dict(champion.params)})
        write_json(self.dir / "checkpoint.json", state)

    def write_report(self, text: str) -> None:
        write_atomic(self.dir / "report.md", text)
