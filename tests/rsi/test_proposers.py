import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from arena.rsi.proposers import PROPOSERS, describe_change, make_proposer
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


def test_a_change_note_ignores_round_trip_noise() -> None:
    space = [ParamSpec("a", "float", 0.0, 100.0, 20.0), ParamSpec("b", "float", 0.0, 1.0, 0.5)]
    note = describe_change({"a": 20.0, "b": 0.5}, {"a": 20.00000000000003, "b": 0.75}, space)
    assert note == "b 0.5->0.75"
    assert describe_change({"a": 20.0, "b": 0.5}, {"a": 20.0, "b": 0.5}, space) == "no change"


def test_pbt_members_move_on_dev_wins_and_the_worst_copies_the_best() -> None:
    space = (ParamSpec("a", "float", 0.0, 1.0, 0.5), ParamSpec("b", "float", 0.0, 1.0, 0.5))
    pbt = make_proposer("pbt", batch=4, exploit=1)
    champ = champion(space)
    rng = np.random.default_rng(3)
    cands = [pbt.propose(champ, History(1, (), (champ,)), space, rng) for _ in range(4)]
    diffs = [0.5, -0.2, 0.1, -0.4]
    pbt.observe(
        [
            Feedback(1, c, False, "screened", fake_dev(c, d))
            for c, d in zip(cands, diffs, strict=True)
        ]
    )
    members = pbt.state()["members"]
    best = [cands[0].params[p.name] for p in space]
    assert [round(x, 9) for x in members[0]["u"]] == [round(x, 9) for x in best]
    assert members[0]["score"] == 0.5 and members[2]["score"] == 0.1
    assert members[1]["score"] == 0.0  # a dev loss leaves the member where it was
    assert members[3]["u"] == members[0]["u"] and members[3]["score"] == 0.5
    assert members[3]["sigma"] in (pytest.approx(0.15 * 0.8), pytest.approx(0.15 * 1.25))


def test_pbt_scores_follow_the_new_champion_after_an_accept() -> None:
    space = (ParamSpec("a", "float", 0.0, 1.0, 0.5),)
    pbt = make_proposer("pbt", batch=2, exploit=1)
    champ = champion(space)
    rng = np.random.default_rng(0)
    cands = [pbt.propose(champ, History(1, (), (champ,)), space, rng) for _ in range(2)]
    pbt.observe(
        [
            Feedback(1, cands[0], True, "holdout", fake_dev(cands[0], 0.6)),
            Feedback(1, cands[1], False, "screened", fake_dev(cands[1], 0.2)),
        ]
    )
    members = pbt.state()["members"]
    accepted_u = pytest.approx([cands[0].params["a"]])
    # the accepted point is now the champion, so it scores 0; the other member, 0.4 behind
    # it, is the worst and copies it
    assert [m["score"] for m in members] == [pytest.approx(0.0)] * 2
    assert members[0]["u"] == accepted_u and members[1]["u"] == accepted_u


def test_pbt_rejects_a_population_too_small_to_exploit() -> None:
    with pytest.raises(ValueError):
        make_proposer("pbt", batch=1)
    with pytest.raises(ValueError):
        make_proposer("pbt", batch=4, exploit=3)
