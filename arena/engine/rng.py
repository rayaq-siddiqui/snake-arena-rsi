"""A tiny, explicit, JSON-serialisable RNG (SplitMix64).

The engine never touches global randomness: its only random state is one integer stored
in ``GameState``, advanced by the pure functions below.
"""

from __future__ import annotations

import hashlib

MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15


def next_u64(state: int) -> tuple[int, int]:
    """Advance ``state`` and return ``(new_state, random 64-bit value)``."""
    state = (state + _GOLDEN) & MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return state, z ^ (z >> 31)


def randbelow(state: int, n: int) -> tuple[int, int]:
    """Return ``(new_state, uniform integer in [0, n))`` using rejection sampling."""
    if n <= 0:
        raise ValueError("n must be positive")
    limit = (1 << 64) - ((1 << 64) % n)
    while True:
        state, value = next_u64(state)
        if value < limit:
            return state, value % n


def derive_seed(*parts: object) -> int:
    """Derive an independent 64-bit seed from any printable parts."""
    digest = hashlib.sha256(repr(parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")
