import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from arena.rsi.proposers import PROPOSERS, make_proposer
from arena.rsi.types import Candidate, Feedback, History, PairedResult, ParamSpec, validate


@st.composite
def spaces(draw: st.DrawFn) -> tuple[ParamSpec, ...]:
    out = []
    for i in range(draw(st.integers(1, 6))):
        kind = draw(st.sampled_from(["float", "int", "log"]))
        if kind == "int":
            lo = draw(st.integers(-50, 50))
            hi = lo + draw(st.integers(1, 100))
            out.append(ParamSpec(f"p{i}", "int", lo, hi, draw(st.integers(lo, hi))))
        elif kind == "log":
            lo = draw(st.floats(1e-4, 1.0))
            hi = lo * draw(st.floats(1.5, 1e4))
            out.append(ParamSpec(f"p{i}", "float", lo, hi, lo, "log"))
        else:
            lo = draw(st.floats(-1e3, 1e3))
            hi = lo + draw(st.floats(1e-3, 1e3))
            out.append(ParamSpec(f"p{i}", "float", lo, hi, hi))
    return tuple(out)


def champion(space: tuple[ParamSpec, ...], gen: int = 0) -> Candidate:
    return Candidate.make({p.name: p.default for p in space}, None, gen, "baseline", "")


def fake_dev(c: Candidate, diff: float) -> PairedResult:
    return PairedResult((1, 2), (diff, diff), (0.0, 0.0))


@pytest.mark.parametrize("name", sorted(PROPOSERS))
@settings(max_examples=40, deadline=None)
@given(space=spaces(), seed=st.integers(0, 2**32 - 1))
def test_every_proposal_is_within_bounds(name: str, space: tuple, seed: int) -> None:
    proposer = make_proposer(name)
    rng = np.random.default_rng(seed)
    champ = champion(space)
    archive: list[Candidate] = [champ]
    for g in range(1, 6):
        history = History(g, (), tuple(archive))
        cands = [proposer.propose(champ, history, space, rng) for _ in range(proposer.batch)]
        for c in cands:
            assert validate(c.params, space) == [], c.params
            assert c.parent_id == champ.id and c.generation == g and c.proposer == name
        accepted = cands[0]
        proposer.observe(
            [
                Feedback(g, c, c is accepted, "holdout", fake_dev(c, 1.0 - i))
                for i, c in enumerate(cands)
            ]
        )
        champ = accepted
        archive.append(champ)


@pytest.mark.parametrize("name", sorted(PROPOSERS))
def test_state_round_trips_and_resumes_identically(name: str) -> None:
    space = tuple(ParamSpec(f"x{i}", "float", -1.0, 1.0, 0.0) for i in range(4))
    a = make_proposer(name)
    champ = champion(space)
    rng = np.random.default_rng(3)
    for g in range(1, 7):
        c = a.propose(champ, History(g, (), (champ,)), space, rng)
        extra = [a.propose(champ, History(g, (), (champ,)), space, rng) for _ in range(a.batch - 1)]
        fb = [Feedback(g, c, g % 3 == 0, "holdout", fake_dev(c, 0.5))]
        fb += [Feedback(g, e, False, "screened", fake_dev(e, -0.5)) for e in extra]
        a.observe(fb)
    b = make_proposer(name)
    b.load_state(a.state())
    assert b.state() == a.state()
    hist = History(7, (), (champ,))
    pa = a.propose(champ, hist, space, np.random.default_rng(9))
    pb = b.propose(champ, hist, space, np.random.default_rng(9))
    assert pa == pb


def test_hill_climb_follows_the_one_fifth_rule() -> None:
    space = (ParamSpec("x", "float", 0.0, 1.0, 0.5),)
    p = make_proposer("gaussian_hill_climb", sigma=0.1)
    champ = champion(space)
    rng = np.random.default_rng(0)
    c = p.propose(champ, History(1, (), ()), space, rng)
    p.observe([Feedback(1, c, True, "holdout", None)])
    assert p.sigma == pytest.approx(0.15)
    c = p.propose(champ, History(2, (), ()), space, rng)
    p.observe([Feedback(2, c, False, "dev", None)])
    assert p.sigma == pytest.approx(0.135)
    assert p.weights["x"] > 1.0
    for g in range(100):
        c = p.propose(champ, History(g, (), ()), space, rng)
        p.observe([Feedback(g, c, False, "dev", None)])
    assert p.sigma == p.sigma_min


def test_coordinate_search_halves_delta_after_a_fruitless_cycle() -> None:
    space = tuple(ParamSpec(f"x{i}", "float", 0.0, 1.0, 0.5) for i in range(2))
    p = make_proposer("coordinate_search", delta=0.2)
    champ = champion(space)
    rng = np.random.default_rng(0)
    seen = []
    for g in range(1, 5):
        c = p.propose(champ, History(g, (), ()), space, rng)
        seen.append(c.params)
        p.observe([Feedback(g, c, False, "dev", None)])
    assert seen[0]["x0"] == pytest.approx(0.7) and seen[1]["x0"] == pytest.approx(0.3)
    assert seen[2]["x1"] == pytest.approx(0.7) and seen[3]["x1"] == pytest.approx(0.3)
    assert p.delta == pytest.approx(0.1)


def test_unknown_proposers_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown proposer"):
        make_proposer("telepathy")
