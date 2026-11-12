"""A tiny standard-library web server for watching matches (phase 1 spec, section 9).

The browser asks for frames in order; the server computes ticks only when asked. Pausing
or changing speed only changes how fast the browser asks, so a seed always plays out the
same way no matter how it is watched.
"""

from __future__ import annotations

import collections
import json
import secrets
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from arena.agents import DEFAULT_POLICY, LINEUPS, POLICIES, Policy, make_policy
from arena.agents.registry import expand_policies, snake_labels
from arena.engine import Event, GameConfig, GameState, new_game, rank, step
from arena.sim.match import Match
from arena.sim.replay import build_replay, check_schema, load_replay

MAX_SESSIONS = 16
FRAME_BUFFER = 20_000
MAX_FRAMES_PER_REQUEST = 5_000
VIEWER_DEFAULTS = GameConfig(width=20, height=20, score_target=10)
VIEWER_POLICY = "personalities"
STATIC_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}


@dataclass(frozen=True)
class Roster:
    """Extra named policies and lineups for the viewer, such as archived champions.

    ``lineups`` may have any seat count; picking one sets the number of snakes.
    """

    policies: dict[str, Callable[[], Policy]] = field(default_factory=dict)
    labels: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    lineups: dict[str, list[str]] = field(default_factory=dict)

    def make(self, name: str) -> Policy:
        factory = self.policies.get(name)
        return factory() if factory is not None else make_policy(name)

    def expand(self, spec: str, count: int) -> list[str]:
        spec = spec.strip()
        if spec in self.lineups:
            return list(self.lineups[spec])
        names = [n.strip() for n in spec.split(",") if n.strip()]
        if not names or any(n in LINEUPS or n not in self.policies for n in names):
            return expand_policies(spec, count)
        names = names * count if len(names) == 1 else names
        if len(names) != count:
            raise ValueError(f"need 1 or {count} policy names, got {len(names)}")
        return names

    def snake_labels(
        self, snake_ids: list[str], policies: list[str]
    ) -> list[tuple[str, str | None]]:
        out = snake_labels(snake_ids, policies)
        counts = {p: policies.count(p) for p in policies}
        for i, (sid, name) in enumerate(zip(snake_ids, policies, strict=True)):
            if name in self.labels:
                label, colour = self.labels[name]
                out[i] = (label if counts[name] == 1 else f"{label} {sid}", colour)
        return out


NO_ROSTER = Roster()


def frame(state: GameState, events: list[Event]) -> dict[str, Any]:
    return {
        "t": state.tick,
        "snakes": [
            {
                "id": s.id,
                "b": [list(c) for c in s.body],
                "life": s.life_id,
                "k": s.kills,
                "d": s.deaths,
                "r": s.respawn_in,
                "lt": s.life_ticks,
                "at": s.alive_ticks,
            }
            for s in state.snakes
        ],
        "ev": [e.to_dict() for e in events if e.kind in ("death", "kill", "spawn", "match_end")],
    }


class Session:
    """One match being watched: either live (policies choose) or a stored replay."""

    def __init__(
        self,
        config: GameConfig,
        seed: int,
        policies: list[str] | None = None,
        replay: dict[str, Any] | None = None,
        roster: Roster = NO_ROSTER,
    ) -> None:
        self.id = secrets.token_hex(6)
        self.lock = threading.Lock()
        self.config = config
        self.seed = seed
        self.roster = roster
        self.match: Match | None = None
        self.replay_actions: list[list[str | None]] = []
        if replay is not None:
            check_schema(replay)
            self.mode = "replay"
            self.policies = [replay["policies"][sid]["name"] for sid in config.snake_ids]
            self.replay_actions = replay["actions"]
            self.state, events = new_game(config, seed)
        else:
            self.mode = "live"
            self.policies = policies or [DEFAULT_POLICY] * config.num_snakes
            self.match = Match([roster.make(n) for n in self.policies], seed, config, record=True)
            self.state = self.match.state
            events = list(self.match.events)
        self.frames: collections.deque[dict[str, Any]] = collections.deque(maxlen=FRAME_BUFFER)
        self.frames.append(frame(self.state, events))

    @property
    def finished(self) -> bool:
        if self.mode == "replay":
            return self.state.finished or self.state.tick >= len(self.replay_actions)
        return self.state.finished

    def _advance(self) -> list[Event]:
        if self.match is not None:
            events = self.match.advance()
            self.state = self.match.state
            return events
        actions = self.replay_actions[self.state.tick]
        ids = self.config.snake_ids
        moves = {sid: a for sid, a in zip(ids, actions, strict=True) if a is not None}
        self.state, events = step(self.state, moves)
        return events

    def frames_from(self, start: int, count: int) -> list[dict[str, Any]]:
        count = max(1, min(count, MAX_FRAMES_PER_REQUEST))
        with self.lock:
            while self.state.tick < start + count - 1 and not self.finished:
                events = self._advance()
                self.frames.append(frame(self.state, events))
            oldest = self.frames[0]["t"]
            if start < oldest:
                raise LookupError(f"tick {start} is no longer buffered (oldest {oldest})")
            return [f for f in self.frames if start <= f["t"] < start + count]

    def finish(self) -> dict[str, Any]:
        """Play to the end without keeping frames, for an instant result."""
        with self.lock:
            last_events: list[Event] = []
            while not self.finished:
                last_events = self._advance()
            self.frames.clear()
            final = frame(self.state, last_events)
            self.frames.append(final)
            return final

    def meta(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mode": self.mode,
            "seed": self.seed,
            "config": self.config.to_dict(),
            "snakes": [
                {"id": sid, "policy": name, "label": label, "color": color}
                for sid, name, (label, color) in zip(
                    self.config.snake_ids,
                    self.policies,
                    self.roster.snake_labels(list(self.config.snake_ids), self.policies),
                    strict=True,
                )
            ],
            "lineup": self.lineup(),
            "replay_ticks": len(self.replay_actions) if self.mode == "replay" else None,
        }

    def lineup(self) -> str | None:
        """The policy spec that recreates these seats, if there is one."""
        for name, seats in self.roster.lineups.items():
            if seats == self.policies:
                return name
        for name in LINEUPS:
            if expand_policies(name, self.config.num_snakes) == self.policies:
                return name
        return self.policies[0] if len(set(self.policies)) == 1 else None

    def summary(self) -> dict[str, Any]:
        return {
            "tick": self.state.tick,
            "finished": self.finished,
            "end_reason": self.state.end_reason,
            "standings": [s.to_dict() for s in rank(self.state.snakes)],
        }

    def replay(self) -> dict[str, Any]:
        if self.match is None:
            raise LookupError("this session is already a replay")
        with self.lock:
            return build_replay(self.match)


class App:
    def __init__(
        self,
        defaults: GameConfig,
        seed: int,
        policy: str,
        startup_replay: dict[str, Any] | None,
        roster: Roster = NO_ROSTER,
    ) -> None:
        self.roster = roster
        self.defaults = defaults
        self.seed = seed
        self.policy = policy
        self.startup_replay = startup_replay
        self.sessions: collections.OrderedDict[str, Session] = collections.OrderedDict()
        self.lock = threading.Lock()

    def add(self, session: Session) -> Session:
        with self.lock:
            self.sessions[session.id] = session
            while len(self.sessions) > MAX_SESSIONS:
                self.sessions.popitem(last=False)
        return session

    def get(self, session_id: str) -> Session:
        with self.lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise LookupError("unknown or expired match; start a new one")
        return session

    def info(self) -> dict[str, Any]:
        return {
            "defaults": self.defaults.to_dict(),
            "seed": self.seed,
            "policy": self.policy,
            "policies": [*self.roster.lineups, *LINEUPS, *sorted(POLICIES), *self.roster.policies],
            "startup_replay": self.startup_replay is not None,
        }

    def create(self, body: dict[str, Any]) -> Session:
        if body.get("mode") == "startup_replay":
            if self.startup_replay is None:
                raise ValueError("no replay was given on the command line")
            return self.add(replay_session(self.startup_replay))
        if body.get("mode") == "replay":
            return self.add(replay_session(body["replay"]))
        overrides = dict(body.get("config", {}))
        spec = body.get("policies") or body.get("policy", self.policy)
        if isinstance(spec, list):
            spec = ",".join(str(n) for n in spec)
        if str(spec).strip() in self.roster.lineups:
            overrides["num_snakes"] = len(self.roster.lineups[str(spec).strip()])
        config = GameConfig.from_dict({**self.defaults.to_dict(), **overrides})
        names = self.roster.expand(str(spec), config.num_snakes)
        seed = int(body.get("seed", self.seed))
        return self.add(Session(config, seed, policies=names, roster=self.roster))


def replay_session(replay: dict[str, Any]) -> Session:
    check_schema(replay)
    config = GameConfig.from_dict(replay["config"])
    return Session(config, int(replay["seed"]), replay=replay)


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    static = resources.files("arena.viz") / "static"

    class Handler(BaseHTTPRequestHandler):
        server_version = "SnakeArena/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            pass

        def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(data, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_error_json(self, status: HTTPStatus, message: str) -> None:
            self.send_json({"error": message}, status)

        def read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 64 * 1024 * 1024:
                raise ValueError("request body too large")
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            return data

        def do_GET(self) -> None:
            url = urlparse(self.path)
            parts = [p for p in url.path.split("/") if p]
            try:
                if not parts:
                    return self.send_static("index.html")
                if parts[0] == "static" and len(parts) == 2:
                    return self.send_static(parts[1])
                if parts == ["api", "info"]:
                    return self.send_json(app.info())
                if len(parts) == 4 and parts[:2] == ["api", "match"]:
                    session = app.get(parts[2])
                    if parts[3] == "frames":
                        query = parse_qs(url.query)
                        start = int(query.get("from", ["0"])[0])
                        count = int(query.get("count", ["200"])[0])
                        frames = session.frames_from(start, count)
                        return self.send_json(
                            {"frames": frames, "finished": session.finished}
                            | ({"summary": session.summary()} if session.finished else {})
                        )
                    if parts[3] == "replay":
                        return self.send_json(session.replay())
                    if parts[3] == "summary":
                        return self.send_json(session.summary())
                self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
            except LookupError as exc:
                self.send_error_json(HTTPStatus.GONE, str(exc))
            except ValueError as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

        def do_POST(self) -> None:
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            try:
                if parts == ["api", "match"]:
                    session = app.create(self.read_json())
                    return self.send_json(session.meta() | {"frame": session.frames[0]})
                if len(parts) == 4 and parts[:2] == ["api", "match"] and parts[3] == "finish":
                    session = app.get(parts[2])
                    final = session.finish()
                    return self.send_json({"frame": final, "summary": session.summary()})
                self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
            except LookupError as exc:
                self.send_error_json(HTTPStatus.GONE, str(exc))
            except (ValueError, KeyError, TypeError) as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

        def send_static(self, name: str) -> None:
            suffix = Path(name).suffix
            resource = static / name
            if suffix not in STATIC_TYPES or "/" in name or not resource.is_file():
                return self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
            body = resource.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", STATIC_TYPES[suffix] + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def make_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    config: GameConfig = VIEWER_DEFAULTS,
    seed: int = 42,
    policy: str = VIEWER_POLICY,
    replay_path: str | None = None,
    roster: Roster = NO_ROSTER,
) -> ThreadingHTTPServer:
    replay = load_replay(replay_path) if replay_path else None
    app = App(config, seed, policy, replay, roster)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server


def serve(
    host: str,
    port: int,
    config: GameConfig,
    seed: int,
    policy: str,
    replay_path: str | None = None,
    open_browser: bool = True,
    roster: Roster = NO_ROSTER,
) -> int:
    server = make_server(host, port, config, seed, policy, replay_path, roster)
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"Snake Arena viewer running at {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
