from arena.rsi.seeds import SeedPools, rng_for


def test_pools_are_disjoint_and_reproducible() -> None:
    pools = SeedPools.generate(7, dev_pool=500, dev_pairs=20, holdout_pairs=10, final_pairs=30)
    dev, hold, final = set(pools.dev), set(pools.holdout), set(pools.final)
    assert len(dev) == 500 and len(hold) == 2 * 10 * 10 and len(final) == 30
    assert not dev & hold and not dev & final and not hold & final
    assert pools == SeedPools.generate(
        7, dev_pool=500, dev_pairs=20, holdout_pairs=10, final_pairs=30
    )
    assert pools != SeedPools.generate(
        8, dev_pool=500, dev_pairs=20, holdout_pairs=10, final_pairs=30
    )
    assert SeedPools.from_dict(pools.to_dict()) == pools


def test_dev_slices_are_fresh_each_generation_and_come_from_the_dev_pool() -> None:
    pools = SeedPools.generate(1, dev_pool=1000, dev_pairs=50)
    a, b = pools.dev_slice(1, 1), pools.dev_slice(1, 2)
    assert len(set(a)) == 50 and set(a) <= set(pools.dev) and a != b
    assert pools.dev_slice(1, 1) == a and pools.dev_slice(1, 1, index=1) != a


def test_holdout_rotates_every_few_generations() -> None:
    pools = SeedPools.generate(1, dev_pool=100, holdout_pairs=5, holdout_blocks=3, holdout_rotate=4)
    blocks = [pools.holdout_block(g) for g in range(1, 14)]
    assert blocks[0] == blocks[3] != blocks[4]
    assert blocks[0] == blocks[12]
    decide, extend = blocks[0]
    assert len(decide) == len(extend) == 5 and not set(decide) & set(extend)


def test_random_streams_depend_on_every_input() -> None:
    draw = lambda *a: rng_for(*a).integers(0, 2**32)  # noqa: E731
    assert draw(1, 2, "x") == draw(1, 2, "x")
    assert len({draw(1, 2, "x"), draw(1, 3, "x"), draw(2, 2, "x"), draw(1, 2, "y")}) == 4
