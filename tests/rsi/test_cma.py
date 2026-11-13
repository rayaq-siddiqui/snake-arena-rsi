"""The (1+1)-CMA-ES proposer: step-size control and covariance learning."""

import numpy as np
import pytest

from arena.rsi.proposers import OnePlusOneCMA, make_proposer
from arena.rsi.types import Candidate, Feedback, History, PairedResult, ParamSpec

SPACE = tuple(ParamSpec(f"x{i}", "float", -1.0, 1.0, 0.0) for i in range(4))
CHAMP = Candidate.make({p.name: 0.0 for p in SPACE}, None, 0, "baseline", "")


def dev(diff: float) -> PairedResult:
    diffs = [diff + 0.01 * (i % 3) for i in range(20)]
    return PairedResult(tuple(range(20)), tuple(diffs), (0.0,) * 20)


def step(p: OnePlusOneCMA, g: int, accepted: bool, diff: float, forced: list[float] | None = None):
    c = p.propose(CHAMP, History(g, (), (CHAMP,)), SPACE, np.random.default_rng(g))
    if forced is not None:
        p._steps[c.id] = forced
    p.observe([Feedback(g, c, accepted, "holdout" if accepted else "dev", dev(diff))])


def test_sigma_grows_on_successes_and_shrinks_on_failures_within_bounds() -> None:
    p = make_proposer("cma_es")
    assert isinstance(p, OnePlusOneCMA)
    for g in range(30):
        step(p, g, True, 1.0)
    grown = p.sigma
    assert grown > 0.15 and grown <= p.sigma_max
    for g in range(300):
        step(p, g, False, 0.0)
    assert p.sigma == pytest.approx(p.sigma_min)


def test_accepted_steps_teach_the_covariance_a_direction() -> None:
    p = OnePlusOneCMA()
    for g in range(40):
        step(p, g, True, 1.0, forced=[1.0, 1.0, 0.0, 0.0])
    c = np.array(p.cov)
    corr = c[0, 1] / np.sqrt(c[0, 0] * c[1, 1])
    assert corr > 0.5 and c[0, 0] > c[2, 2] and c[2, 3] == pytest.approx(0.0)


def test_clearly_worse_steps_shrink_the_covariance_and_keep_it_positive_definite() -> None:
    p = OnePlusOneCMA()
    for g in range(200):
        step(p, g, False, -1.0, forced=[2.0, 0.0, 0.0, 0.0])
    c = np.array(p.cov)
    assert c[0, 0] < c[1, 1] / 10 and c[1, 1] == pytest.approx(c[2, 2])
    np.linalg.cholesky(c)
    assert np.linalg.cond(c) <= OnePlusOneCMA.max_condition
    passive = OnePlusOneCMA(active=False)
    for g in range(20):
        step(passive, g, False, -1.0, forced=[2.0, 0.0, 0.0, 0.0])
    assert np.allclose(passive.cov, np.eye(4))


def test_screened_and_validate_feedback_teach_nothing() -> None:
    p = OnePlusOneCMA()
    c = p.propose(CHAMP, History(1, (), (CHAMP,)), SPACE, np.random.default_rng(0))
    before = p.state()
    p.observe([Feedback(1, c, False, "validate", None)])
    assert p.state() == before
