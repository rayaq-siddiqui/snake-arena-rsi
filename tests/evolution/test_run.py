import hashlib
import json
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest
from evo_helpers import TINY, AlwaysAccept, lineage_files, tiny_evolution

from arena.agents.scorer import ScoringPolicy
from arena.evolution.run import Evolution, load_champion, provenance
from arena.rsi.loop import Run
from arena.rsi.proposers import GaussianHillClimb
from arena.rsi.store import code_hash
from arena.rsi.types import Candidate, Feedback, History, ParamSpec

ROOT = Path(__file__).resolve().parents[2]


def test_a_run_writes_lineages_and_versioned_params(tmp_path: Path) -> None:
    r = tiny_evolution(tmp_path, generations=2, rule=AlwaysAccept()).run()
    assert r.generations == 2 and r.stop_reason == "generation budget"
    for name in ("hunter", "predictor"):
        assert (tmp_path / "lineages" / name / "report.md").exists()
        versions = sorted(p.name for p in (tmp_path / "params" / name).glob("v*.json"))
        assert versions == ["v1.json", "v2.json", "v3.json"]
        latest = json.loads((tmp_path / "params" / f"{name}.json").read_text())
        assert latest["version"] == 3
        champion = load_champion(tmp_path, name)
        assert dict(champion.params) == latest["params"]
        assert champion.build().choose_action is not None
    timing = (tmp_path / "timing.jsonl").read_text().splitlines()
    assert [json.loads(t)["generation"] for t in timing] == [1, 2]


def test_a_run_records_what_its_numbers_depend_on(tmp_path: Path) -> None:
    tiny_evolution(tmp_path, generations=1).run()
    meta = json.loads((tmp_path / "evolution.json").read_text())
    assert {"code_hash", "arena_hash", "python", "numpy"} <= meta.keys()
    assert meta["arena_hash"] != meta["code_hash"]


def test_the_arena_hash_covers_policies_and_their_params(tmp_path: Path) -> None:
    copy = tmp_path / "arena"
    shutil.copytree(ROOT / "arena", copy, ignore=shutil.ignore_patterns("__pycache__"))
    before = code_hash(copy, ("*.py", "*.json"))
    assert before == provenance()["arena_hash"]
    params = copy / "agents" / "params" / "hunter.json"
    params.write_text(params.read_text() + " ")
    assert code_hash(copy, ("*.py", "*.json")) != before


def test_a_time_budget_counts_every_generation_over_resumes(tmp_path: Path) -> None:
    tiny_evolution(tmp_path, generations=1).run()
    spent = Evolution.seconds(tiny_evolution(tmp_path))
    r = tiny_evolution(tmp_path, generations=3, max_seconds=spent).run()
    assert r.generations == 1 and r.stop_reason == "time budget"
    assert {x.stop_reason for x in r.lineages.values()} == {"time budget"}
    r = tiny_evolution(tmp_path, generations=2, max_seconds=spent + 1e9).run()
    assert r.generations == 2 and r.stop_reason == "generation budget"


def test_an_episode_budget_stops_every_lineage(tmp_path: Path) -> None:
    r = tiny_evolution(tmp_path, generations=5, max_episodes=1).run()
    assert r.generations == 1 and r.stop_reason == "episode budget"


def test_context_freezes_champions_from_the_previous_generation(tmp_path: Path) -> None:
    evo = tiny_evolution(tmp_path, generations=2, rule=AlwaysAccept())
    evo.run()
    evo._open()
    hunter = 0
    for g in (0, 1, 2):
        ctx = evo.context(g)
        assert ctx.champions[hunter].version == g + 1
        assert [e.version for e in ctx.halls[hunter]] == list(range(1, g + 2))
        assert ctx.reference[hunter].version == 1
    assert evo.context(2).champions[1].policy == "survivor"


def test_results_do_not_depend_on_the_worker_count(tmp_path: Path) -> None:
    tiny_evolution(tmp_path / "one", workers=1).run()
    tiny_evolution(tmp_path / "three", workers=3).run()
    one = lineage_files(tmp_path / "one")
    assert one and one == lineage_files(tmp_path / "three")


def test_kill_mid_generation_and_resume_matches_an_uninterrupted_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tiny_evolution(tmp_path / "whole", generations=3, rule=AlwaysAccept()).run()
    real_commit = Run.commit
    calls = {"n": 0}

    def dying_commit(self: Run, pending: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 4:  # generation 2: hunter committed, predictor not
            raise KeyboardInterrupt
        real_commit(self, pending)

    monkeypatch.setattr(Run, "commit", dying_commit)
    with pytest.raises(KeyboardInterrupt):
        tiny_evolution(tmp_path / "cut", generations=3, rule=AlwaysAccept()).run()
    monkeypatch.setattr(Run, "commit", real_commit)
    tiny_evolution(tmp_path / "cut", generations=3, rule=AlwaysAccept()).run()
    for name in ("generations.jsonl", "champion.json"):
        assert lineage_files(tmp_path / "whole", name) == lineage_files(tmp_path / "cut", name)


def test_resume_refuses_a_different_run(tmp_path: Path) -> None:
    tiny_evolution(tmp_path, generations=1).run()
    with pytest.raises(ValueError, match="different evolution run"):
        tiny_evolution(tmp_path, generations=1, run_seed=5).run()


def _repo_digest() -> str:
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    h = hashlib.sha256()
    for name in sorted(f for f in files if f):
        path = ROOT / name.decode()
        if path.is_file():
            h.update(name + b"\0" + path.read_bytes())
    return h.hexdigest()


def test_a_run_touches_nothing_outside_its_directory(tmp_path: Path) -> None:
    before = _repo_digest()
    tiny_evolution(tmp_path, generations=2, rule=AlwaysAccept()).run()
    assert _repo_digest() == before


class Spy(GaussianHillClimb):
    """Records every seed a proposer could see."""

    seen: ClassVar[set[int]] = set()

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        for f in history.feedback:
            if f.dev is not None:
                Spy.seen.update(f.dev.seeds)
        return super().propose(champion, history, space, rng)

    def observe(self, feedback: Sequence[Feedback]) -> None:
        for f in feedback:
            if f.dev is not None:
                Spy.seen.update(f.dev.seeds)
        super().observe(feedback)


def test_the_proposer_never_sees_holdout_or_final_seeds(tmp_path: Path) -> None:
    Spy.seen = set()
    tiny_evolution(tmp_path, generations=3, proposer=lambda _: Spy(sigma=0.5)).run()
    assert Spy.seen
    for name in ("hunter", "predictor"):
        pools = json.loads((tmp_path / "lineages" / name / "seeds.json").read_text())
        assert not Spy.seen & (set(pools["holdout"]) | set(pools["final"]))


class Fixed(GaussianHillClimb):
    def __init__(self, change: Mapping[str, float]) -> None:
        super().__init__()
        self.change = dict(change)

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        params = {**champion.params, **self.change}
        return Candidate.make(params, champion.id, history.generation, "fixed", "broken")


def test_out_of_bounds_parameters_are_never_promoted(tmp_path: Path) -> None:
    r = tiny_evolution(
        tmp_path, generations=2, proposer=lambda _: Fixed({"space_cap": 10_000.0})
    ).run()
    assert all(x.accepted == 0 for x in r.lineages.values())
    rec = json.loads(
        (tmp_path / "lineages" / "hunter" / "generations.jsonl").read_text().split("\n")[0]
    )
    assert rec["decision"]["stage"] == "validate" and "outside" in rec["decision"]["rationale"]


def test_a_policy_that_raises_is_never_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ScoringPolicy.choose_action

    def choose(self: ScoringPolicy, obs: Any) -> Any:
        if self.params.get("trap_margin") == 4.5:
            raise RuntimeError("poisoned candidate")
        return real(self, obs)

    monkeypatch.setattr(ScoringPolicy, "choose_action", choose)
    r = tiny_evolution(
        tmp_path, generations=2, proposer=lambda _: Fixed({"trap_margin": 4.5})
    ).run()
    assert all(x.accepted == 0 for x in r.lineages.values())
    rec = json.loads(
        (tmp_path / "lineages" / "hunter" / "generations.jsonl").read_text().split("\n")[0]
    )
    assert "failures" in rec["decision"]["rationale"]


def test_profiles_are_labelled() -> None:
    assert TINY.name == "tiny"
    assert isinstance(tiny_evolution(Path("unused")), Evolution)


def test_the_in_memory_hall_matches_the_records_after_a_resume(tmp_path: Path) -> None:
    def from_records(evo: Evolution, name: str, upto: int) -> list[str]:
        lin = evo.lineages[name]
        by_id = {m.id: m for m in lin.run.store.archive.members}
        accepted = [
            by_id[r["champion_after"]].id
            for r in lin.records()
            if r["decision"]["accept"] and r["generation"] <= upto
        ]
        return [lin.run.baseline.id, *accepted]

    live = tiny_evolution(tmp_path, generations=2, rule=AlwaysAccept())
    live.run()
    resumed = tiny_evolution(tmp_path, generations=2, rule=AlwaysAccept())
    resumed._open()
    for evo in (live, resumed):
        for name, lin in evo.lineages.items():
            for upto in (0, 1, 2):
                assert [c.id for c in lin.hall(upto)] == from_records(evo, name, upto)
    assert len(resumed.lineages["hunter"].hall(2)) == 3
