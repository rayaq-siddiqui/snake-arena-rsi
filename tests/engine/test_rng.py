import json

import pytest

from arena.engine.rng import derive_seed, next_u64, randbelow


def sequence(seed: int, n: int) -> list[int]:
    out = []
    for _ in range(n):
        seed, value = next_u64(seed)
        out.append(value)
    return out


def test_same_seed_same_sequence() -> None:
    assert sequence(42, 50) == sequence(42, 50)


def test_different_seeds_differ() -> None:
    assert sequence(1, 10) != sequence(2, 10)


def test_randbelow_stays_in_range_and_covers_it() -> None:
    state, seen = 7, set()
    for _ in range(2000):
        state, v = randbelow(state, 10)
        assert 0 <= v < 10
        seen.add(v)
    assert seen == set(range(10))


def test_randbelow_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        randbelow(1, 0)


def test_derive_seed_is_stable_and_independent() -> None:
    assert derive_seed(42, "policy", "s0") == derive_seed(42, "policy", "s0")
    assert derive_seed(42, "policy", "s0") != derive_seed(42, "policy", "s1")
    assert derive_seed(42, "spawn") != derive_seed(42, "policy", "s0")


def test_state_is_json_serialisable() -> None:
    state, _ = next_u64(derive_seed(3))
    assert json.loads(json.dumps(state)) == state
