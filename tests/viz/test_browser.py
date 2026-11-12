"""Runs tests/viz/smoke.mjs in headless Chromium when Node and Playwright are available."""

import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from arena.viz.server import make_server

SCRIPT = Path(__file__).with_name("smoke.mjs")


def node_env() -> dict[str, str] | None:
    if shutil.which("node") is None or shutil.which("npm") is None:
        return None
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    env = {**os.environ, "NODE_PATH": root}
    probe = subprocess.run(
        ["node", "-e", "require('playwright')"], env=env, capture_output=True, text=True
    )
    return env if probe.returncode == 0 else None


def test_viewer_in_a_real_browser() -> None:
    env = node_env()
    if env is None:
        pytest.skip("node with playwright is not available")
    server = make_server(port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        done = subprocess.run(
            ["node", str(SCRIPT), url], env=env, capture_output=True, text=True, timeout=120
        )
        assert done.returncode == 0, done.stdout + done.stderr
    finally:
        server.shutdown()
        server.server_close()
