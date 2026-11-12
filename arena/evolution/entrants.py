"""Snakes as plain data, so they can cross process boundaries and be stored as JSON.

An ``Entrant`` names a policy and, for a personality, the exact parameter values it plays
with. ``build`` turns one back into a fresh policy object for one game.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from arena.agents.base import Policy
from arena.agents.params import ParamSet, load_params
from arena.agents.registry import PERSONALITIES, POLICIES, STYLES, make_policy
from arena.agents.scorer import ScoringPolicy
from arena.rsi.types import ParamSpec

ParamItems = tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class Entrant:
    policy: str
    params: ParamItems | None = None
    version: int = 1
    label: str = ""

    @staticmethod
    def personality(
        name: str, params: Mapping[str, float], version: int, label: str = ""
    ) -> Entrant:
        items = tuple(sorted((k, float(v)) for k, v in params.items()))
        return Entrant(name, items, version, label or f"{STYLES[name][0]} v{version}")

    def build(self) -> Policy:
        if self.params is None:
            return make_policy(self.policy)
        cls = POLICIES[self.policy]
        assert isinstance(cls, type) and issubclass(cls, ScoringPolicy)
        return cls(ParamSet(self.policy, self.version, dict(self.params)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "params": dict(self.params) if self.params is not None else None,
            "version": self.version,
            "label": self.label,
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> Entrant:
        params = d.get("params")
        items = tuple(sorted((k, float(v)) for k, v in params.items())) if params else None
        return Entrant(d["policy"], items, int(d.get("version", 1)), d.get("label", ""))


def personality_class(name: str) -> type[ScoringPolicy]:
    if name not in PERSONALITIES:
        raise ValueError(f"{name!r} is not a personality; choose from {', '.join(PERSONALITIES)}")
    cls = POLICIES[name]
    assert isinstance(cls, type) and issubclass(cls, ScoringPolicy)
    return cls


def param_specs(name: str, start: Mapping[str, float] | None = None) -> tuple[ParamSpec, ...]:
    """A personality's bounded ``ParamSpace`` as the RSI framework's ``ParamSpec`` list.

    The default of each spec is the value the lineage starts from (its params file), so
    a proposer's first step is taken from the hand-set snake, never from a midpoint.
    """
    space = personality_class(name).param_space
    values = space.validate(start if start is not None else space.defaults())
    return tuple(
        ParamSpec(p.name, p.kind, float(p.low), float(p.high), float(values[p.name]))
        for p in space.params
    )


def hand_set(name: str) -> dict[str, float]:
    """The phase 2 parameter values shipped in ``arena/agents/params/<name>.json``."""
    space = personality_class(name).param_space
    return {k: float(v) for k, v in load_params(name, space).params.items()}
