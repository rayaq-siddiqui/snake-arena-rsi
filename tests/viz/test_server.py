import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from arena.agents import make_policy
from arena.engine import GameConfig
from arena.sim.match import simulate_match
from arena.viz.server import make_server


@pytest.fixture
def base_url() -> Iterator[str]:
    server = make_server(port=0, policy="random_safe")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(url: str) -> Any:
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def post(url: str, body: dict[str, Any]) -> Any:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


SMALL = {"width": 16, "height": 16, "score_target": 3, "max_ticks": 3000}


def play_all(base_url: str, match_id: str, chunk: int = 250) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    tick = 1
    while True:
        data = get(f"{base_url}/api/match/{match_id}/frames?from={tick}&count={chunk}")
        frames += data["frames"]
        if data["finished"] and (not data["frames"] or data["frames"][-1]["t"] < tick + chunk):
            return frames
        tick = frames[-1]["t"] + 1


def test_index_and_static_files_are_served(base_url: str) -> None:
    with urllib.request.urlopen(base_url + "/") as r:
        assert b"<canvas" in r.read()
    for name in ("app.js", "style.css"):
        with urllib.request.urlopen(f"{base_url}/static/{name}") as r:
            assert r.status == 200


def test_info_has_viewer_defaults(base_url: str) -> None:
    info = get(base_url + "/api/info")
    assert info["defaults"]["score_target"] == 10
    assert "random_safe" in info["policies"] and "personalities" in info["policies"]


def test_personality_seats_carry_names_and_colours(base_url: str) -> None:
    meta = post(base_url + "/api/match", {"seed": 3, "config": SMALL, "policy": "personalities"})
    assert meta["lineup"] == "personalities"
    assert [s["label"] for s in meta["snakes"]] == [
        "Hunter",
        "Survivor",
        "Trapper",
        "Predictor",
        "Opportunist",
    ]
    assert len({s["color"] for s in meta["snakes"]}) == 5
    meta = post(base_url + "/api/match", {"seed": 3, "config": SMALL, "policy": "random_safe"})
    assert meta["lineup"] == "random_safe"


def test_live_match_matches_headless_simulation(base_url: str) -> None:
    meta = post(base_url + "/api/match", {"seed": 9, "config": SMALL})
    assert meta["frame"]["t"] == 0 and len(meta["snakes"]) == 5
    frames = play_all(base_url, meta["id"])
    assert [f["t"] for f in frames] == list(range(1, len(frames) + 1))
    headless = simulate_match(
        [make_policy("random_safe") for _ in range(5)], 9, GameConfig(**SMALL)
    )
    final = {s["id"]: (s["k"], s["d"]) for s in frames[-1]["snakes"]}
    assert final == {s.snake: (s.kills, s.deaths) for s in headless.standings}
    assert frames[-1]["t"] == headless.ticks


def test_chunk_size_does_not_change_the_game(base_url: str) -> None:
    a = play_all(base_url, post(base_url + "/api/match", {"seed": 5, "config": SMALL})["id"], 7)
    b = play_all(base_url, post(base_url + "/api/match", {"seed": 5, "config": SMALL})["id"], 900)
    assert a == b


def test_finish_jumps_to_the_end(base_url: str) -> None:
    meta = post(base_url + "/api/match", {"seed": 2, "config": SMALL})
    data = post(f"{base_url}/api/match/{meta['id']}/finish", {})
    assert data["summary"]["finished"]
    assert data["summary"]["end_reason"] in {"score_target", "tick_cap"}


def test_downloaded_replay_plays_back_identically(base_url: str) -> None:
    meta = post(base_url + "/api/match", {"seed": 6, "config": SMALL})
    live = play_all(base_url, meta["id"])
    replay = get(f"{base_url}/api/match/{meta['id']}/replay")
    again = post(base_url + "/api/match", {"mode": "replay", "replay": replay})
    assert again["mode"] == "replay"
    assert play_all(base_url, again["id"]) == live


def test_bad_requests_are_reported(base_url: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base_url + "/api/match", {"config": {"width": 3}})
    assert exc.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as exc:
        get(base_url + "/api/match/nope/frames?from=1")
    assert exc.value.code == 410
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base_url + "/api/match", {"policy": "nope"})
    assert exc.value.code == 400
