import json
from pathlib import Path

import numpy as np
from evo_helpers import tiny_evolution
from test_run import AlwaysAccept

from arena.cli import main
from arena.evolution.report import load_lineage, verdict
from arena.rsi.accept import bootstrap_ci
from arena.rsi.seeds import rng_for


def test_report_numbers_match_the_stored_records(tmp_path: Path) -> None:
    tiny_evolution(tmp_path, generations=2, rule=AlwaysAccept()).run()
    assert main(["report", str(tmp_path), "--workers", "1"]) == 0
    data = json.loads((tmp_path / "report.json").read_text())
    final = json.loads((tmp_path / "final.json").read_text())
    md = (tmp_path / "report.md").read_text()
    assert (tmp_path / "progress.svg").read_text().startswith("<svg")
    for name, lin in data["lineages"].items():
        view = load_lineage(tmp_path / "lineages" / name)
        assert lin["generations"] == len(view.records) == 2
        assert lin["accepted"] == sum(r["decision"]["accept"] for r in view.records)
        assert lin["versions"] == len(view.hall) == 3
        assert lin["final"] == final["lineages"][name]["final"]
        assert [d["rationale"] for d in lin["decisions"]] == [
            r["decision"]["rationale"] for r in view.records
        ]
        for pr in lin["progress"]:
            assert len(pr["kills_per_1k"]) == len(view.final_seeds)
            assert pr["mean"] == sum(pr["kills_per_1k"]) / len(pr["kills_per_1k"])
            lo, hi = bootstrap_ci(
                np.asarray(pr["kills_per_1k"]), rng_for(pr["version"], 0, f"progress-{name}"), 2000
            )
            assert pr["ci"] == [lo, hi]
        assert [c["versus"] for c in lin["cycle_check"]] == [1, 2]
        assert verdict(lin["final"]) in md
    assert "tiny profile: a reduced setting" in md
    assert sum(map(sum, data["matrix"]["kills"])) >= 0


def test_verdicts_follow_the_interval() -> None:
    assert verdict(None).startswith("no change")
    assert verdict({"ci": [0.1, 0.3]}) == "improved"
    assert verdict({"ci": [-0.3, -0.1]}) == "got worse"
    assert verdict({"ci": [-0.1, 0.3]}) == "no significant change"
