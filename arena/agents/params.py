"""Named, bounded personality parameters stored as small JSON files (phase 2 spec, section 1).

Phase 4 tunes a snake by writing a new version of its JSON file and nothing else, so every
value is checked against its declared bounds when it is loaded.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

PARAMS_DIR = Path(__file__).parent / "params"


@dataclass(frozen=True)
class Param:
    name: str
    default: float
    low: float
    high: float
    kind: Literal["float", "int"] = "float"

    def __post_init__(self) -> None:
        if not self.low <= self.default <= self.high:
            raise ValueError(
                f"{self.name}: default {self.default} outside [{self.low}, {self.high}]"
            )

    def check(self, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{self.name}: expected a number, got {value!r}")
        if self.kind == "int" and value != int(value):
            raise ValueError(f"{self.name}: expected an integer, got {value!r}")
        if not self.low <= value <= self.high:
            raise ValueError(f"{self.name}: {value} is outside [{self.low}, {self.high}]")
        return int(value) if self.kind == "int" else float(value)


@dataclass(frozen=True)
class ParamSpace:
    params: tuple[Param, ...]

    def __post_init__(self) -> None:
        names = [p.name for p in self.params]
        if len(set(names)) != len(names):
            raise ValueError("duplicate parameter names")

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.params)

    def defaults(self) -> dict[str, float]:
        return {p.name: p.default for p in self.params}

    def validate(self, values: Mapping[str, Any]) -> dict[str, float]:
        """Check every value against its bounds; missing names take their defaults."""
        known = {p.name: p for p in self.params}
        unknown = sorted(set(values) - set(known))
        if unknown:
            raise ValueError(f"unknown parameters: {', '.join(unknown)}")
        return {
            p.name: p.check(values[p.name]) if p.name in values else p.default for p in self.params
        }


@dataclass(frozen=True)
class ParamSet:
    name: str
    version: int
    params: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "params": dict(self.params)}


def params_path(name: str, directory: Path | None = None) -> Path:
    return (directory or PARAMS_DIR) / f"{name}.json"


def parse_params(data: Mapping[str, Any], space: ParamSpace, expect_name: str) -> ParamSet:
    if data.get("name") != expect_name:
        raise ValueError(f"params file is for {data.get('name')!r}, expected {expect_name!r}")
    version = data.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError(f"params version must be a positive integer, got {version!r}")
    raw = data.get("params", {})
    if not isinstance(raw, Mapping):
        raise ValueError("params must be an object")
    return ParamSet(expect_name, version, space.validate(raw))


def load_params(name: str, space: ParamSpace, path: Path | None = None) -> ParamSet:
    path = path or params_path(name)
    return parse_params(json.loads(path.read_text()), space, name)


def save_params(params: ParamSet, space: ParamSpace, path: Path | None = None) -> Path:
    checked = ParamSet(params.name, params.version, space.validate(params.params))
    path = path or params_path(params.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checked.to_dict(), indent=2) + "\n")
    return path
