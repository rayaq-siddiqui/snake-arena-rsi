import numpy as np

from arena.rsi.accept import GuardMetric, PairedBootstrapRule, bootstrap_ci, relative_gain
from arena.rsi.types import PairedResult

RULE = PairedBootstrapRule()


def result(
    diffs: list[float], base: float = 10.0, failures: int = 0, guards: dict | None = None
) -> PairedResult:
    n = len(diffs)
    return PairedResult(
        tuple(range(n)),
        tuple(base + d for d in diffs),
        (base,) * n,
        {"guards": guards} if guards else {},
        failures,
    )


def rng() -> np.random.Generator:
    return np.random.default_rng(0)


GOOD = [1.0 + 0.1 * ((i % 5) - 2) for i in range(100)]


def test_clear_improvement_is_accepted_with_a_rationale() -> None:
    d = RULE.decide(result(GOOD), result(GOOD), rng())
    assert d.accept and d.stage == "holdout" and d.rationale.startswith("accepted")
    assert d.stats["holdout"]["ci"][0] > 0 and d.stats["holdout"]["n"] == 100


def test_dev_screen_rejects_a_non_positive_mean() -> None:
    d = RULE.decide(result([-0.1] * 100), result(GOOD), rng())
    assert not d.accept and d.stage == "dev"
    assert RULE.passes_dev(result(GOOD)) is None


def test_interval_reaching_zero_is_rejected() -> None:
    noisy = [2.0 if i % 2 else -1.5 for i in range(100)]
    d = RULE.decide(result(GOOD), result(noisy), rng())
    assert not d.accept and "interval reaches 0" in d.rationale


def test_gain_below_the_minimum_is_rejected() -> None:
    tiny = [0.1 + 0.001 * (i % 3) for i in range(100)]
    d = RULE.decide(result(GOOD), result(tiny), rng())
    assert d.stats["holdout"]["ci"][0] > 0
    assert not d.accept and "minimum gain" in d.rationale


def test_a_worse_guard_metric_is_rejected() -> None:
    rule = PairedBootstrapRule(guards=(GuardMetric("deaths", 0.15),))
    ok = rule.decide(result(GOOD), result(GOOD, guards={"deaths": (1.1, 1.0)}), rng())
    bad = rule.decide(result(GOOD), result(GOOD, guards={"deaths": (1.2, 1.0)}), rng())
    missing = rule.decide(result(GOOD), result(GOOD), rng())
    assert ok.accept and not bad.accept and "guard worse" in bad.rationale
    assert not missing.accept and "not reported" in missing.rationale
    lower_bad = GuardMetric("kills", 0.1, higher_is_worse=False)
    assert lower_bad.violated(0.8, 1.0) and not lower_bad.violated(0.95, 1.0)


def test_failures_are_rejected_on_dev_and_on_holdout() -> None:
    assert RULE.decide(result(GOOD, failures=1), result(GOOD), rng()).stage == "dev"
    d = RULE.decide(result(GOOD), result(GOOD, failures=2), rng())
    assert not d.accept and "failures" in d.rationale


def test_extension_is_offered_only_for_a_promising_straddle() -> None:
    straddle = [2.0 if i % 2 else -1.5 for i in range(100)]
    assert RULE.wants_extension(result(straddle), rng())
    assert not RULE.wants_extension(result(GOOD), rng())
    assert not RULE.wants_extension(result([-1.0] * 100), rng())
    assert not PairedBootstrapRule(allow_extension=False).wants_extension(result(straddle), rng())
    d = RULE.decide(result(GOOD), result(straddle).extend(result(GOOD)), rng(), extended=True)
    assert d.stats["holdout"]["extended"] and d.stats["holdout"]["n"] == 200


def test_bootstrap_is_seeded_and_sensible() -> None:
    diffs = np.array(GOOD)
    assert bootstrap_ci(diffs, rng()) == bootstrap_ci(diffs, rng())
    lo, hi = bootstrap_ci(diffs, rng())
    assert lo < diffs.mean() < hi and hi - lo < 0.1


def test_relative_gain_handles_signs_and_zero() -> None:
    assert relative_gain(-9.0, -10.0) == 0.1
    assert relative_gain(11.0, 10.0) == 0.1
    assert relative_gain(1.0, 0.0) == float("inf") and relative_gain(0.0, 0.0) == 0.0


def test_rule_round_trips() -> None:
    rule = PairedBootstrapRule(guards=(GuardMetric("deaths", 0.15, slack=0.01),))
    assert PairedBootstrapRule.from_dict(rule.to_dict()) == rule
