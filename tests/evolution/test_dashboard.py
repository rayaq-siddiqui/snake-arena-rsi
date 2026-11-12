import html
import json
from pathlib import Path

import pytest
from evo_helpers import AlwaysAccept, tiny_evolution

from arena.cli import main
from arena.evolution import dashboard
from arena.evolution.report import load_run


def test_a_run_keeps_a_dashboard_that_matches_its_records(tmp_path: Path) -> None:
    tiny_evolution(tmp_path, generations=2, rule=AlwaysAccept()).run()
    page = (tmp_path / "dashboard.html").read_text()
    assert "http-equiv='refresh'" not in page
    assert "reduced setting" in page
    _, views = load_run(tmp_path)
    for view in views.values():
        assert f">v{len(view.hall)}<" in page
        for rec in view.records:
            assert html.escape(rec["decision"]["rationale"], quote=True) in page
        rows = dashboard.attempts(view)
        assert [a.accepted for a in rows] == [r["decision"]["accept"] for r in view.records]
    timing = (tmp_path / "timing.jsonl").read_text().splitlines()
    assert len(timing) == 2 and page.count("<svg") >= 3 * len(views) + 2


def test_a_running_dashboard_reloads_and_the_cli_rewrites_it(tmp_path: Path) -> None:
    tiny_evolution(tmp_path, generations=1).run()
    (tmp_path / "final.json").unlink()
    (tmp_path / "dashboard.html").unlink()
    assert main(["dashboard", str(tmp_path)]) == 0
    assert "http-equiv='refresh'" in (tmp_path / "dashboard.html").read_text()


def test_a_broken_dashboard_never_stops_a_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(run_dir: object) -> Path:
        raise RuntimeError("disk full")

    monkeypatch.setattr(dashboard, "write", boom)
    r = tiny_evolution(tmp_path, generations=1).run()
    assert r.generations == 1 and json.loads((tmp_path / "final.json").read_text())


def test_float_noise_is_not_shown_as_a_change() -> None:
    note = "sigma 0.15: w_territory 20->20, w_space 6->103.5, w_straightness 0.01->0.01"
    assert dashboard._clean(note) == "w_space 6->103.5"
    assert dashboard._clean("uniform random point") == "uniform random point"
