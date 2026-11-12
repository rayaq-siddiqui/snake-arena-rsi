"""Look up policies by name so the CLI and viewer can build them from strings."""

from __future__ import annotations

from collections.abc import Callable

from arena.agents.base import Policy
from arena.agents.random_policies import RandomSafe, RandomUniform

POLICIES: dict[str, Callable[[], Policy]] = {
    RandomSafe.name: RandomSafe,
    RandomUniform.name: RandomUniform,
}

DEFAULT_POLICY = RandomSafe.name


def make_policy(name: str) -> Policy:
    try:
        return POLICIES[name]()
    except KeyError:
        known = ", ".join(sorted(POLICIES))
        raise ValueError(f"unknown policy {name!r}; known: {known}") from None
