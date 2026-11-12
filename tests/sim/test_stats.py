from arena.sim.stats import bootstrap_mean_ci, mean


def test_bootstrap_interval_brackets_the_mean_and_is_seeded() -> None:
    values = [0.0, 1.0, 2.0, 3.0, 4.0] * 20
    lo, hi = bootstrap_mean_ci(values)
    assert lo < mean(values) < hi
    assert (lo, hi) == bootstrap_mean_ci(values)
    assert bootstrap_mean_ci([5.0] * 10) == (5.0, 5.0)
    assert bootstrap_mean_ci([]) == (0.0, 0.0)


def test_interval_excludes_zero_only_for_a_clear_effect() -> None:
    assert bootstrap_mean_ci([1.0, 2.0, 1.5, 0.5] * 25)[0] > 0
    assert bootstrap_mean_ci([1.0, -1.0, 0.5, -0.5] * 25)[0] < 0
