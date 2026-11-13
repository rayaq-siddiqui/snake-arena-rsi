import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from library_helpers import LINEUP, make_library

from arena.viz.library import Library
from arena.viz.server import make_server


@pytest.fixture
def library(tmp_path: Path) -> Path:
    make_library(tmp_path)
    return tmp_path


@pytest.fixture
def base_url(library: Path) -> Iterator[str]:
    server = make_server(port=0, policy="random_safe", library=[library])
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


def last_frame(base_url: str, match_id: str) -> dict[str, Any]:
    return post(f"{base_url}/api/match/{match_id}/finish", {})["frame"]


def test_index_lists_replays_and_tournament_rows(library: Path) -> None:
    entries = Library([library]).entries()
    kinds = sorted(e.kind for e in entries)
    assert kinds == ["replay", "replay", "tournament", "tournament", "tournament"]
    for e in entries:
        assert e.ticks > 0 and e.size == "12x12"
        assert e.winner is None or e.winner in e.policies
    tour = [e for e in entries if e.kind == "tournament"]
    assert {e.seed for e in tour} == {3, 4, 5}
    assert all(e.policies == tuple(LINEUP) for e in tour)


def test_filters_and_facets(library: Path) -> None:
    lib = Library([library])
    every = lib.query()
    assert every["total"] == 5
    assert "hunter" in every["facets"]["policy"]
    assert lib.query(policy="hunter")["total"] == 3
    assert lib.query(policy="random_safe")["total"] == 2
    for reason in every["facets"]["end_reason"]:
        assert all(e["end_reason"] == reason for e in lib.query(end_reason=reason)["entries"])
    for winner in every["facets"]["winner"]:
        assert all(e["winner"] == winner for e in lib.query(winner=winner)["entries"])
    assert lib.query(limit=2)["total"] == 5 and len(lib.query(limit=2)["entries"]) == 2


def test_a_changed_file_is_reindexed(library: Path) -> None:
    lib = Library([library])
    assert lib.query()["total"] == 5
    path = library / "tournament" / "matches.jsonl"
    path.write_text(path.read_text().splitlines()[0] + "\n")
    assert lib.query()["total"] == 3


def test_paths_cannot_leave_the_library(library: Path) -> None:
    with pytest.raises(ValueError):
        Library([library]).match_request("r:0/../../etc/passwd")


def test_opening_entries_reproduces_the_stored_games(base_url: str) -> None:
    data = get(base_url + "/api/library")
    for entry in data["entries"]:
        meta = post(base_url + "/api/match", {"mode": "library", "entry": entry["id"]})
        assert meta["entry"] == entry["id"]
        assert meta["mode"] == ("replay" if entry["kind"] == "replay" else "live")
        final = last_frame(base_url, meta["id"])
        assert final["t"] == entry["ticks"]
        assert sum(s["k"] for s in final["snakes"]) == entry["kills"]


def test_bookmarks_round_trip_and_seek(base_url: str, library: Path) -> None:
    entry = get(base_url + "/api/library?policy=hunter")["entries"][0]["id"]
    assert get(base_url + "/api/bookmarks") == []
    marks = post(base_url + "/api/bookmarks", {"entry": entry, "tick": 40, "note": "close call"})
    assert marks == [{"id": 1, "entry": entry, "tick": 40, "note": "close call"}]
    post(base_url + "/api/bookmarks", {"entry": entry, "tick": 7})
    assert json.loads((library / "bookmarks.json").read_text())[1]["tick"] == 7
    meta = post(base_url + "/api/match", {"mode": "library", "entry": entry})
    frames = get(f"{base_url}/api/match/{meta['id']}/frames?from=40&count=1")["frames"]
    assert [f["t"] for f in frames] == [40]
    assert [m["id"] for m in post(base_url + "/api/bookmarks/1/delete", {})] == [2]
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base_url + "/api/bookmarks", {"entry": "r:0/missing.json", "tick": 1})
    assert exc.value.code == 410


def test_library_is_off_without_a_folder() -> None:
    server = make_server(port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        assert get(url + "/api/info")["library"] is False
        with pytest.raises(urllib.error.HTTPError) as exc:
            get(url + "/api/library")
        assert exc.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
