"""The viewer's replay browser (vision section 7): find stored games, filter, bookmark.

Two kinds of stored game are listed:

- replay files (``*.json`` written by ``run-match --replay`` or the viewer's Download
  button). They hold every action, so they play back exactly whatever the code is now.
- rows of a tournament's ``matches.jsonl``. A row stores the seed, the config and the
  policy names, so the viewer re-simulates it; with unchanged code and parameters that
  is the same game (the determinism rule), and the list marks these as re-simulated.

The index is rebuilt for a file only when its size or modification time changes.
Bookmarks are kept in ``bookmarks.json`` in the first library folder.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arena.sim.replay import load_replay

REPLAY_PREFIX = b'{"schema_version":'
MAX_FILES = 5_000
SKIP_DIRS = {"archive", "lineages", "params", "__pycache__", ".git", ".venv", "node_modules"}


@dataclass(frozen=True)
class Entry:
    """One stored game, as the replay list shows it."""

    id: str
    kind: str  # "replay" (exact actions) or "tournament" (re-simulated from its seed)
    file: str
    seed: int
    policies: tuple[str, ...]
    winner: str | None  # the winning seat's policy name; None on a tie for first
    end_reason: str | None
    ticks: int
    kills: int
    size: str  # "WxH"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"policies": list(self.policies)}


def _winner(standings: list[dict[str, Any]], policy_of: dict[str, str]) -> str | None:
    top = [s for s in standings if s.get("rank") == 1]
    return policy_of.get(top[0]["snake"]) if len(top) == 1 else None


def replay_entry(path: Path, rel: str) -> Entry | None:
    with path.open("rb") as f:
        if f.read(len(REPLAY_PREFIX)) != REPLAY_PREFIX:
            return None
    data = json.loads(path.read_text())
    config = data["config"]
    ids = [f"s{i}" for i in range(int(config["num_snakes"]))]
    policy_of = {sid: str(data["policies"][sid]["name"]) for sid in ids}
    standings = data.get("final_standings", [])
    return Entry(
        id=f"r:{rel}",
        kind="replay",
        file=rel,
        seed=int(data["seed"]),
        policies=tuple(policy_of[sid] for sid in ids),
        winner=_winner(standings, policy_of),
        end_reason=data.get("end_reason"),
        ticks=len(data["actions"]),
        kills=sum(int(s.get("kills", 0)) for s in standings),
        size=f"{config['width']}x{config['height']}",
    )


def tournament_entries(path: Path, rel: str) -> list[Entry]:
    out = []
    for i, line in enumerate(path.read_text().splitlines()):
        if not line.strip():
            continue
        row = json.loads(line)
        config = row["config"]
        policies = [str(p) for p in row["policies"]]
        policy_of = {f"s{j}": p for j, p in enumerate(policies)}
        standings = row.get("standings", [])
        out.append(
            Entry(
                id=f"t:{rel}#{i}",
                kind="tournament",
                file=rel,
                seed=int(row["seed"]),
                policies=tuple(policies),
                winner=_winner(standings, policy_of),
                end_reason=row.get("end_reason"),
                ticks=int(row.get("ticks", 0)),
                kills=sum(int(s.get("kills", 0)) for s in standings),
                size=f"{config['width']}x{config['height']}",
            )
        )
    return out


class Library:
    """Stored games under one or more folders, plus the viewer's bookmarks."""

    def __init__(self, roots: list[str | Path]) -> None:
        self.roots = [Path(r) for r in roots]
        self.lock = threading.Lock()
        self._cache: dict[Path, tuple[tuple[int, int], list[Entry]]] = {}

    @property
    def bookmarks_path(self) -> Path | None:
        return self.roots[0] / "bookmarks.json" if self.roots else None

    def _files(self) -> list[tuple[Path, str]]:
        found: list[tuple[Path, str]] = []
        for n, root in enumerate(self.roots):
            if not root.is_dir():
                continue
            stack = [root]
            while stack and len(found) < MAX_FILES:
                folder = stack.pop()
                for child in sorted(folder.iterdir()):
                    if child.is_dir() and child.name not in SKIP_DIRS:
                        stack.append(child)
                    elif child.suffix in (".json", ".jsonl") and child.name != "bookmarks.json":
                        found.append((child, f"{n}/{child.relative_to(root).as_posix()}"))
        return found

    def _index(self, path: Path, rel: str) -> list[Entry]:
        stat = path.stat()
        key = (stat.st_size, stat.st_mtime_ns)
        cached = self._cache.get(path)
        if cached is not None and cached[0] == key:
            return cached[1]
        entries: list[Entry] = []
        try:
            if path.name == "matches.jsonl":
                entries = tournament_entries(path, rel)
            elif path.suffix == ".json":
                entry = replay_entry(path, rel)
                entries = [entry] if entry is not None else []
        except (OSError, ValueError, KeyError, TypeError):
            entries = []
        self._cache[path] = (key, entries)
        return entries

    def entries(self) -> list[Entry]:
        with self.lock:
            out: list[Entry] = []
            for path, rel in self._files():
                out.extend(self._index(path, rel))
            return out

    def query(
        self,
        winner: str | None = None,
        policy: str | None = None,
        end_reason: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Filtered entries plus the values each filter can take."""
        every = self.entries()
        hits = [
            e
            for e in every
            if (not winner or e.winner == winner)
            and (not policy or policy in e.policies)
            and (not end_reason or e.end_reason == end_reason)
        ]
        limit = max(1, min(limit, 500))
        return {
            "total": len(hits),
            "entries": [e.to_dict() for e in hits[offset : offset + limit]],
            "facets": {
                "winner": sorted({e.winner for e in every if e.winner}),
                "policy": sorted({p for e in every for p in e.policies}),
                "end_reason": sorted({e.end_reason for e in every if e.end_reason}),
            },
            "roots": [str(r) for r in self.roots],
        }

    def _path(self, file: str) -> Path:
        n, _, rel = file.partition("/")
        root = self.roots[int(n)].resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root):
            raise ValueError("path outside the library")
        if not path.is_file():
            raise LookupError(f"{file} is no longer in the library")
        return path

    def match_request(self, entry_id: str) -> dict[str, Any]:
        """The body ``App.create`` needs to open this stored game."""
        kind, _, rest = entry_id.partition(":")
        if kind == "r":
            return {"mode": "replay", "replay": load_replay(self._path(rest))}
        if kind == "t":
            file, _, row = rest.rpartition("#")
            lines = self._path(file).read_text().splitlines()
            data = json.loads(lines[int(row)])
            return {"seed": data["seed"], "config": data["config"], "policies": data["policies"]}
        raise ValueError(f"unknown library entry {entry_id!r}")

    def bookmarks(self) -> list[dict[str, Any]]:
        path = self.bookmarks_path
        if path is None or not path.exists():
            return []
        data: list[dict[str, Any]] = json.loads(path.read_text())
        return data

    def add_bookmark(self, entry: str, tick: int, note: str = "") -> list[dict[str, Any]]:
        path = self.bookmarks_path
        if path is None:
            raise ValueError("the viewer was started without a library folder")
        self.match_request(entry)
        with self.lock:
            marks = self.bookmarks()
            next_id = max((int(m["id"]) for m in marks), default=0) + 1
            marks.append({"id": next_id, "entry": entry, "tick": int(tick), "note": note[:200]})
            self._save(path, marks)
            return marks

    def remove_bookmark(self, bookmark_id: int) -> list[dict[str, Any]]:
        path = self.bookmarks_path
        if path is None:
            return []
        with self.lock:
            marks = [m for m in self.bookmarks() if int(m["id"]) != bookmark_id]
            self._save(path, marks)
            return marks

    @staticmethod
    def _save(path: Path, marks: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(marks, indent=1))
        tmp.replace(path)
