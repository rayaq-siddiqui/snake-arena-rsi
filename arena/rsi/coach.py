"""A language-model coach that rewrites a harness's own search settings (opt-in).

``AdaptiveHarness`` already learns, from its candidates' dev games, which operator to use,
which parameters to move and how many candidates to try. The coach works one level up:
every few generations it reads what the harness has learned (its operator rewards, its
parameter weights and the journal of recent generations) together with a short brief on
what the policy is for, and returns a *harness patch*:

* ``operator_bias``: a per-operator nudge, -1..+1, added to the harness's bandit score;
* ``param_priors``: the weights, 0.25..4, the harness starts from and decays back to, i.e.
  the strategy prior it searches around;
* ``explore``: the bandit's exploration constant, 0.2..3;
* ``max_batch``: the most candidates per generation, 2..8.

What keeps it inside the rules (phase 3 spec, sections 4 and 6):

- It sees only what the harness sees: dev results and accept flags, never seeds, holdout
  or final numbers. It changes how candidates are *proposed*, never how they are judged.
- A patch is numbers only. Unknown keys and names are dropped and every value is clipped,
  so a reply cannot run anything or reach the acceptance rule, evaluator or seeds.
- It is budgeted in dollars, and every call is appended to an audit log with the prompt,
  the reply, the cost and the patch that was applied.
- A failed, refused or unparsable call applies no patch; the harness carries on alone.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from arena.rsi.llm import DEFAULT_PRICES, PROVIDERS, Complete, _first_json_object

SYSTEM = (
    "You coach an automated search harness that tunes a game-playing policy's numeric "
    "parameters. The harness picks a search operator for each candidate with a bandit, "
    "weights which parameters its steps touch, and grows its batch when nothing beats the "
    "champion. You see the policy's goal, what the harness has learned and how its recent "
    "candidates did against the champion on development games. Reply with only a JSON "
    'object: {"operator_bias": {operator: number -1..1}, "param_priors": {parameter: '
    'number 0.25..4}, "explore": number 0.2..3, "max_batch": integer 2..8, "rationale": '
    '"two sentences"}. Omit keys you would leave unchanged. Favour operators and '
    "parameters that produced dev wins or accepts, steer away from ones that keep losing, "
    "and keep the policy's goal in mind."
)

LIMITS = {
    "operator_bias": (-1.0, 1.0),
    "param_priors": (0.25, 4.0),
    "explore": (0.2, 3.0),
    "max_batch": (2.0, 8.0),
}


def _clip(value: Any, key: str) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value):
        return None
    lo, hi = LIMITS[key]
    return min(hi, max(lo, float(value)))


def parse_patch(text: str, operators: Sequence[str], params: Sequence[str]) -> dict[str, Any]:
    """The usable part of a reply: known keys and names only, every number clipped."""
    data = _first_json_object(text)
    if not isinstance(data, dict):
        raise ValueError("the reply is not a JSON object")
    patch: dict[str, Any] = {}
    for key, names in (("operator_bias", operators), ("param_priors", params)):
        raw = data.get(key)
        if isinstance(raw, dict):
            kept = {n: v for n in names if (v := _clip(raw.get(n), key)) is not None}
            if kept:
                patch[key] = kept
    for key in ("explore", "max_batch"):
        v = _clip(data.get(key), key)
        if v is not None:
            patch[key] = round(v) if key == "max_batch" else v
    if isinstance(data.get("rationale"), str):
        patch["rationale"] = data["rationale"][:400]
    return patch


class HarnessCoach:
    """Asks a language model for a harness patch; budgeted and audit-logged."""

    def __init__(
        self,
        brief: str,
        every: int = 2,
        complete: Complete | None = None,
        provider: str = "openrouter",
        model: str = "deepseek/deepseek-v4.1-flash",
        max_dollars: float = 0.1,
        prices: tuple[float, float] = DEFAULT_PRICES,
        audit_path: str | Path | None = None,
        label: str = "",
    ) -> None:
        if provider not in PROVIDERS:
            raise ValueError(f"unknown llm provider {provider!r}")
        if every < 1:
            raise ValueError("every must be at least 1")
        self.brief = brief
        self.every = every
        self._complete = complete
        self.provider = provider
        self.model = model
        self.max_dollars = max_dollars
        self.prices = prices
        self.audit_path = Path(audit_path) if audit_path is not None else None
        self.label = label
        self.calls = 0
        self.failures = 0
        self.dollars = 0.0

    def due(self, generation: int) -> bool:
        return generation % self.every == 0 and self.dollars < self.max_dollars

    def _audit(self, record: Mapping[str, Any]) -> None:
        if self.audit_path is None:
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    def advise(
        self,
        generation: int,
        view: Mapping[str, Any],
        operators: Sequence[str],
        params: Sequence[str],
    ) -> dict[str, Any] | None:
        """One call: the patch to apply, or None when the call gave nothing usable."""
        prompt = json.dumps({"goal": self.brief, "generation": generation, **view}, indent=1)
        record: dict[str, Any] = {
            "generation": generation,
            "lineage": self.label,
            "model": self.model,
            "provider": self.provider,
            "prompt": prompt,
        }
        try:
            if self._complete is None:
                self._complete = PROVIDERS[self.provider](self.model)
            reply = self._complete(SYSTEM, prompt)
        except Exception as exc:  # a failed call leaves the harness as it is
            self.failures += 1
            self._audit(record | {"error": repr(exc)})
            return None
        self.calls += 1
        cost = reply.dollars
        if cost is None:
            tokens_in, tokens_out = reply.input_tokens, reply.output_tokens
            cost = (tokens_in * self.prices[0] + tokens_out * self.prices[1]) / 1e6
        self.dollars += cost
        record |= {"reply": reply.text, "dollars": cost}
        try:
            if reply.refused:
                raise ValueError("the model declined")
            patch = parse_patch(reply.text, operators, params)
        except (ValueError, TypeError) as exc:
            self.failures += 1
            self._audit(record | {"error": str(exc)})
            return None
        self._audit(record | {"patch": patch})
        return patch

    def state(self) -> dict[str, Any]:
        return {"calls": self.calls, "failures": self.failures, "dollars": self.dollars}

    def load_state(self, state: Mapping[str, Any]) -> None:
        self.calls = int(state.get("calls", 0))
        self.failures = int(state.get("failures", 0))
        self.dollars = float(state.get("dollars", 0.0))
