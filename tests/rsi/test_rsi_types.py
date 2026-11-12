import pytest

from arena.rsi.types import Candidate, PairedResult, ParamSpec, params_id, validate


def test_unit_mapping_round_trips_and_clips() -> None:
    p = ParamSpec("w", "float", -2.0, 6.0, 0.0)
    assert p.to_unit(-2.0) == 0.0 and p.to_unit(6.0) == 1.0
    assert p.from_unit(p.to_unit(1.5)) == pytest.approx(1.5)
    assert p.from_unit(-0.3) == -2.0 and p.from_unit(1.7) == 6.0


def test_log_scale_is_even_in_log_space() -> None:
    p = ParamSpec("lr", "float", 0.001, 1.0, 0.01, "log")
    assert p.to_unit(0.01) == pytest.approx(1 / 3)
    assert p.from_unit(2 / 3) == pytest.approx(0.1)


def test_int_parameters_round() -> None:
    p = ParamSpec("k", "int", 1, 10, 3)
    assert p.from_unit(0.5) == 6.0
    assert p.check(3.5) is not None and p.check(4) is None


@pytest.mark.parametrize(
    "bad",
    [
        dict(name="x", kind="float", low=1.0, high=0.0, default=0.5),
        dict(name="x", kind="float", low=0.0, high=1.0, default=2.0),
        dict(name="x", kind="float", low=0.0, high=1.0, default=0.5, scale="log"),
        dict(name="x", kind="int", low=0.5, high=3.0, default=1.0),
    ],
)
def test_bad_specs_are_rejected(bad: dict) -> None:
    with pytest.raises(ValueError):
        ParamSpec(**bad)


def test_validate_reports_every_problem() -> None:
    space = (ParamSpec("a", "float", 0, 1, 0.5), ParamSpec("k", "int", 0, 5, 1))
    assert validate({"a": 0.2, "k": 2}, space) == []
    problems = validate({"a": 3.0, "k": 1.5, "zz": 1}, space)
    assert len(problems) == 3 and any("unknown parameter zz" in p for p in problems)
    assert validate({"a": float("nan"), "k": True}, space) != []
    assert "missing parameter k" in validate({"a": 0.1}, space)


def test_candidate_ids_are_content_hashes() -> None:
    a = Candidate.make({"x": 1, "y": 2.0}, None, 0, "t", "")
    b = Candidate.make({"y": 2.0, "x": 1.0}, "p", 3, "u", "other note")
    assert a.id == b.id == params_id({"x": 1.0, "y": 2.0})
    assert Candidate.from_dict(a.to_dict()) == a


def test_paired_results_extend_and_summarise() -> None:
    r = PairedResult((1, 2), (3.0, 5.0), (1.0, 1.0), {"guards": {"deaths": (2.0, 1.0)}})
    assert r.mean_diff == 3.0
    more = PairedResult((3, 4), (1.0, 1.0), (1.0, 1.0), {"guards": {"deaths": (0.0, 1.0)}}, 1)
    both = r.extend(more)
    assert both.seeds == (1, 2, 3, 4) and both.failures == 1
    assert both.guards() == {"deaths": (1.0, 1.0)}
    with pytest.raises(ValueError):
        PairedResult((1,), (1.0, 2.0), (1.0,))
