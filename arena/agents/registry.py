"""Look up policies by name so the CLI and viewer can build them from strings."""

from __future__ import annotations

from collections.abc import Callable

from arena.agents.base import Policy
from arena.agents.hunter import Hunter
from arena.agents.opportunist import Opportunist
from arena.agents.predictor import Predictor
from arena.agents.random_policies import RandomSafe, RandomUniform
from arena.agents.survivor import Survivor
from arena.agents.trapper import Trapper

POLICIES: dict[str, Callable[[], Policy]] = {
    RandomSafe.name: RandomSafe,
    RandomUniform.name: RandomUniform,
    Hunter.name: Hunter,
    Survivor.name: Survivor,
    Trapper.name: Trapper,
    Predictor.name: Predictor,
    Opportunist.name: Opportunist,
}

DEFAULT_POLICY = RandomSafe.name

PERSONALITIES: tuple[str, ...] = (
    Hunter.name,
    Survivor.name,
    Trapper.name,
    Predictor.name,
    Opportunist.name,
)
"""The phase 2 lineup in seat order s0..s4; ``--policy personalities`` expands to it."""

LINEUPS: dict[str, tuple[str, ...]] = {"personalities": PERSONALITIES}


def make_policy(name: str) -> Policy:
    try:
        return POLICIES[name]()
    except KeyError:
        known = ", ".join(sorted(POLICIES))
        raise ValueError(f"unknown policy {name!r}; known: {known}") from None


STYLES: dict[str, tuple[str, str]] = {
    Hunter.name: ("Hunter", "#f7768e"),
    Survivor.name: ("Survivor", "#9ece6a"),
    Trapper.name: ("Trapper", "#e0af68"),
    Predictor.name: ("Predictor", "#7aa2f7"),
    Opportunist.name: ("Opportunist", "#bb9af7"),
}
"""Display name and colour (red, green, yellow, blue, purple) for each personality."""


def expand_policies(spec: str, count: int) -> list[str]:
    """A lineup name, one policy for every snake, or a comma list with one per snake."""
    spec = spec.strip()
    if spec in LINEUPS:
        names = list(LINEUPS[spec])
    else:
        names = [n.strip() for n in spec.split(",") if n.strip()]
    if len(names) == 1:
        names *= count
    if len(names) != count:
        raise ValueError(f"need 1 or {count} policy names, got {len(names)}")
    for name in names:
        make_policy(name)
    return names


def snake_labels(snake_ids: list[str], policies: list[str]) -> list[tuple[str, str | None]]:
    """(label, colour) per snake: personality names and colours, else the snake id.

    A personality that plays more than one seat gets its id appended so labels stay unique.
    """
    counts = {p: policies.count(p) for p in policies}
    out: list[tuple[str, str | None]] = []
    for sid, policy in zip(snake_ids, policies, strict=True):
        if policy in STYLES:
            name, colour = STYLES[policy]
            out.append((name if counts[policy] == 1 else f"{name} {sid}", colour))
        else:
            out.append((sid, None))
    return out
