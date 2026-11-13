"""The optional LLM proposer (phase 3 spec, section 6; plan step 5.5).

Off by default and never needed: the loop runs fully offline with the built-in
proposers. When chosen, it shows a language model the parameter schema, the champion's
values and recent dev-screen results, and asks for one new parameter set as JSON.

What keeps it safe and honest:

- It only ever returns numbers. Unknown names are dropped, missing ones keep the
  champion's value, and every value is clipped to its declared bounds, so a reply can't
  run anything or leave the search space.
- Its prompt is built from ``History`` alone, which carries dev means and accept flags,
  never seeds or holdout numbers. ``tests/rsi/test_llm.py`` checks that no holdout or
  final seed reaches a prompt.
- It is budgeted: a token cap and a dollar cap (checked by the loop as ``Budget.tokens``
  and ``Budget.dollars``, and by the proposer itself), and every call is appended to an
  audit log with the prompt, the reply, the tokens and what was kept.
- If a call fails, is refused, can't be parsed, or the budget is spent, it falls back to
  ``GaussianHillClimb`` for that proposal and says so in the candidate's note.

LLM replies are not reproducible, so a resumed LLM run proposes afresh rather than
replaying; the audit log is the record of what was asked and answered.
"""

from __future__ import annotations

import importlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from arena.rsi.proposers import GaussianHillClimb, describe_change
from arena.rsi.types import Candidate, Feedback, History, ParamSpec

DEFAULT_MODEL = "claude-opus-5-5"
# US dollars per million input / output tokens for DEFAULT_MODEL, used only for the
# dollar budget; pass other prices for another model.
DEFAULT_PRICES = (4.0, 20.0)

SYSTEM = (
    "You tune the numeric parameters of a game-playing policy. Each turn you see the "
    "parameters with their bounds, the current champion's values, and how recent "
    "candidates did on development games against the champion (positive diff = the "
    "candidate scored higher). Propose ONE new parameter set that you expect to beat the "
    "champion. Change a few parameters at a time, stay within bounds, and avoid repeating "
    "candidates that were already rejected. Reply with only a JSON object of the form "
    '{"params": {"name": number, ...}, "rationale": "one sentence"}.'
)


@dataclass(frozen=True)
class Reply:
    """One model answer: its text and what it cost in tokens."""

    text: str
    input_tokens: int
    output_tokens: int
    refused: bool = False


Complete = Callable[[str, str], Reply]
"""``complete(system, prompt)``: one call to a language model."""


def anthropic_complete(model: str = DEFAULT_MODEL, max_tokens: int = 2048) -> Complete:
    """A ``Complete`` backed by the Anthropic Python SDK (``pip install anthropic``).

    Credentials come from the environment the SDK reads (``ANTHROPIC_API_KEY`` or an
    ``ant auth login`` profile). The SDK is imported only here, so the rest of the
    project never depends on it. Server-side refusal fallbacks are switched on, so a
    request a safety classifier declines is retried on a fallback model by the API.
    """
    try:
        anthropic: Any = importlib.import_module("anthropic")
    except ImportError as exc:
        raise RuntimeError(
            "the llm proposer needs the Anthropic SDK: uv pip install anthropic"
        ) from exc
    client = anthropic.Anthropic()

    def complete(system: str, prompt: str) -> Reply:
        response = client.beta.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        usage = response.usage
        return Reply(
            text,
            int(usage.input_tokens),
            int(usage.output_tokens),
            refused=response.stop_reason == "refusal",
        )

    return complete


def build_prompt(
    champion: Candidate, history: History, space: Sequence[ParamSpec], recent: int
) -> str:
    """The proposer's whole view: schema, champion, and recent dev-only feedback."""
    schema = [
        {
            "name": p.name,
            "type": p.kind,
            "low": p.low,
            "high": p.high,
            "scale": p.scale,
            "champion": champion.params[p.name],
        }
        for p in space
    ]
    tried = []
    for f in history.feedback[-recent:] if recent > 0 else ():
        entry: dict[str, Any] = {
            "generation": f.generation,
            "change": describe_change(champion.params, f.candidate.params, space),
            "outcome": "accepted" if f.accepted else f"rejected at {f.stage}",
        }
        if f.dev is not None:
            entry["dev"] = {
                "games": f.dev.n,
                "candidate_mean": round(f.dev.mean_a, 4),
                "champion_mean": round(f.dev.mean_b, 4),
                "diff": round(f.dev.mean_diff, 4),
            }
        tried.append(entry)
    return json.dumps(
        {
            "generation": history.generation,
            "parameters": schema,
            "recent_candidates": tried,
            "accepted_so_far": len(history.archive) - 1,
        },
        indent=1,
    )


def _first_json_object(text: str) -> Any:
    """The first complete JSON object in ``text``. A greedy ``{.*}`` match would run on
    to the last brace, so a reply that adds a note with braces after its JSON fails."""
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            data, _ = decoder.raw_decode(text, m.start())
        except ValueError:
            continue
        return data
    raise ValueError("no JSON object in the reply")


def parse_params(text: str, champion: Candidate, space: Sequence[ParamSpec]) -> dict[str, float]:
    """Numbers only: unknown names dropped, missing ones kept, everything clipped."""
    data = _first_json_object(text)
    proposed = data.get("params", data) if isinstance(data, dict) else None
    if not isinstance(proposed, dict):
        raise ValueError("the reply has no params object")
    params = dict(champion.params)
    for p in space:
        value = proposed.get(p.name)
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if not math.isfinite(value):
            continue
        clipped = min(p.high, max(p.low, float(value)))
        params[p.name] = float(round(clipped)) if p.kind == "int" else clipped
    return params


class LLMProposer:
    """Ask a language model for the next parameter set; numbers only, budgeted, audited."""

    name = "llm"
    batch = 1

    def __init__(
        self,
        complete: Complete | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int | None = None,
        max_dollars: float | None = None,
        prices: tuple[float, float] = DEFAULT_PRICES,
        audit_path: str | Path | None = None,
        recent: int = 12,
    ) -> None:
        self._complete = complete
        self.model = model
        self.max_tokens = max_tokens
        self.max_dollars = max_dollars
        self.prices = prices
        self.audit_path = Path(audit_path) if audit_path is not None else None
        self.recent = recent
        self.fallback = GaussianHillClimb()
        self.calls = 0
        self.tokens = 0
        self.dollars = 0.0
        self.failures = 0

    def spent(self) -> dict[str, float]:
        """What the loop checks against ``Budget.tokens`` and ``Budget.dollars``."""
        return {"tokens": self.tokens, "dollars": self.dollars}

    def _budget_left(self) -> bool:
        if self.max_tokens is not None and self.tokens >= self.max_tokens:
            return False
        return self.max_dollars is None or self.dollars < self.max_dollars

    def _audit(self, record: Mapping[str, Any]) -> None:
        if self.audit_path is None:
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    def propose(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
    ) -> Candidate:
        if not self._budget_left():
            return self._fall_back(champion, history, space, rng, "llm budget spent")
        prompt = build_prompt(champion, history, space, self.recent)
        record: dict[str, Any] = {"generation": history.generation, "model": self.model}
        record["prompt"] = prompt
        try:
            if self._complete is None:
                self._complete = anthropic_complete(self.model)
            reply = self._complete(SYSTEM, prompt)
        except Exception as exc:  # a failed call is a fallback, not a crashed run
            self.failures += 1
            self._audit(record | {"error": repr(exc)})
            return self._fall_back(champion, history, space, rng, "llm call failed")
        self.calls += 1
        self.tokens += reply.input_tokens + reply.output_tokens
        self.dollars += (
            reply.input_tokens * self.prices[0] + reply.output_tokens * self.prices[1]
        ) / 1e6
        record |= {
            "reply": reply.text,
            "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens,
            "refused": reply.refused,
        }
        try:
            if reply.refused:
                raise ValueError("the model declined")
            params = parse_params(reply.text, champion, space)
        except (ValueError, TypeError) as exc:
            self.failures += 1
            self._audit(record | {"error": str(exc)})
            return self._fall_back(champion, history, space, rng, f"llm reply unusable: {exc}")
        note = "llm: " + describe_change(champion.params, params, space)
        self._audit(record | {"params": params})
        return Candidate.make(params, champion.id, history.generation, self.name, note)

    def _fall_back(
        self,
        champion: Candidate,
        history: History,
        space: Sequence[ParamSpec],
        rng: np.random.Generator,
        why: str,
    ) -> Candidate:
        cand = self.fallback.propose(champion, history, space, rng)
        return Candidate.make(
            cand.params, champion.id, history.generation, self.name, f"{why}; {cand.note}"
        )

    def observe(self, feedback: Sequence[Feedback]) -> None:
        self.fallback.observe(feedback)

    def state(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "tokens": self.tokens,
            "dollars": self.dollars,
            "failures": self.failures,
            "fallback": self.fallback.state(),
        }

    def load_state(self, state: Mapping[str, Any]) -> None:
        self.calls = int(state["calls"])
        self.tokens = int(state["tokens"])
        self.dollars = float(state["dollars"])
        self.failures = int(state["failures"])
        self.fallback.load_state(state["fallback"])
