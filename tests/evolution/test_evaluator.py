import os
from concurrent.futures.process import BrokenProcessPool

import pytest

from arena.agents.registry import PERSONALITIES
from arena.evolution.entrants import Entrant, hand_set, param_specs
from arena.evolution.evaluator import (
    MIXTURES,
    Context,
    EvalSettings,
    SnakeEvaluator,
    Workers,
    lineup,
)
from arena.rsi.types import Candidate, validate

TINY = EvalSettings(16, 16, 150)


def reference_context() -> Context:
    ref = tuple(Entrant.personality(p, hand_set(p), 1) for p in PERSONALITIES)
    return Context(ref, tuple((r,) for r in ref), ref)


def test_param_specs_start_from_the_params_file() -> None:
    for name in PERSONALITIES:
        specs = param_specs(name)
        assert validate({p.name: p.default for p in specs}, specs) == []
        assert {p.name: p.default for p in specs} == hand_set(name)


def test_lineups_rotate_seats_and_cover_every_mixture() -> None:
    ctx = reference_context()
    seen = set()
    for seed in range(400):
        seat, mixture, opponents = lineup(ctx, 0, seed)
        assert seat == seed % 5 and len(opponents) == 4
        assert all(o.policy != "hunter" for o in opponents)
        seen.add(mixture)
        assert lineup(ctx, 0, seed) == (seat, mixture, opponents)
    assert seen == set(MIXTURES)


def test_a_candidate_identical_to_the_champion_gives_zero_differences() -> None:
    champ = Candidate.make(hand_set("hunter"), None, 0, "baseline", "")
    twin = Candidate.make(hand_set("hunter"), champ.id, 1, "copy", "")
    ev = SnakeEvaluator("hunter", TINY, Workers(1), reference_context())
    r = ev.evaluate(twin, champ, list(range(12)))
    assert r.n == 12 and all(d == 0 for d in r.diffs)
    assert r.failures == 0
    a, b = r.guards()["deaths_per_1k_alive"]
    assert a == b


def test_results_do_not_depend_on_the_worker_count() -> None:
    champ = Candidate.make(hand_set("trapper"), None, 0, "baseline", "")
    params = dict(champ.params, w_cut_off=-50.0, keep_distance=4.0)
    cand = Candidate.make(params, champ.id, 1, "t", "")
    seeds = list(range(100, 110))
    one = SnakeEvaluator("trapper", TINY, Workers(1), reference_context())
    with Workers(3) as pool:
        three = SnakeEvaluator("trapper", TINY, pool, reference_context())
        r3 = three.evaluate(cand, champ, seeds)
    r1 = one.evaluate(cand, champ, seeds)
    assert r1 == r3


def _die_on_one(x: int) -> int:
    if x == 1:
        os._exit(1)
    return x * 2


def test_workers_start_a_fresh_pool_after_a_worker_dies() -> None:
    with Workers(2) as pool:
        with pytest.raises(BrokenProcessPool):
            pool.map(_die_on_one, [0, 1, 2])
        assert pool.map(_die_on_one, [0, 2, 3]) == [0, 4, 6]
