"""Generic recursive self-improvement framework (phase 3).

Improves anything described by ``ParamSpec`` and an ``Evaluator``. It must not import
the engine, agents or simulator: a test walks the imports to enforce that.
"""

from arena.rsi.accept import GuardMetric, PairedBootstrapRule
from arena.rsi.loop import Run, RunConfig, RunResult
from arena.rsi.proposers import PROPOSERS, make_proposer
from arena.rsi.types import Budget, Candidate, Feedback, History, PairedResult, ParamSpec

__all__ = [
    "PROPOSERS",
    "Budget",
    "Candidate",
    "Feedback",
    "GuardMetric",
    "History",
    "PairedBootstrapRule",
    "PairedResult",
    "ParamSpec",
    "Run",
    "RunConfig",
    "RunResult",
    "make_proposer",
]
