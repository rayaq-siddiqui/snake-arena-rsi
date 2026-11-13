import json
import re
from pathlib import Path

import numpy as np
import pytest

from arena.rsi import Budget, PairedBootstrapRule, Run, RunConfig, make_proposer
from arena.rsi.llm import SYSTEM, LLMProposer, Reply, parse_params
from arena.rsi.toys import NoisyQuadratic
from arena.rsi.types import Candidate, History, ParamSpec

SPACE = (
    ParamSpec("a", "float", -1.0, 1.0, 0.0),
    ParamSpec("k", "int", 1, 10, 5),
)
CHAMP = Candidate.make({"a": 0.0, "k": 5.0}, None, 0, "init", "")


class FakeModel:
    """Answers with a nudged champion, recording every prompt it sees."""

    def __init__(self, tokens: int = 100, refuse: bool = False, fail: bool = False) -> None:
        self.prompts: list[str] = []
        self.tokens = tokens
        self.refuse = refuse
        self.fail = fail

    def __call__(self, system: str, prompt: str) -> Reply:
        assert system == SYSTEM
        self.prompts.append(prompt)
        if self.fail:
            raise ConnectionError("offline")
        view = json.loads(prompt)
        params = {p["name"]: p["champion"] + 0.1 * len(self.prompts) for p in view["parameters"]}
        text = "Sure:\n" + json.dumps({"params": params, "rationale": "nudge"})
        return Reply(text, self.tokens, self.tokens // 2, refused=self.refuse)


def run_with(tmp_path: Path, model: FakeModel, generations: int = 4, **kw: object) -> Run:
    q = NoisyQuadratic(dim=3, problem_seed=1)
    budget = kw.pop("budget", {})
    assert isinstance(budget, dict)
    cfg = RunConfig(
        run_seed=5,
        problem="quadratic",
        dev_pairs=20,
        holdout_pairs=20,
        dev_pool=200,
        final_pairs=20,
        budget=Budget(generations=generations, **budget),
    )
    proposer = LLMProposer(complete=model, audit_path=tmp_path / "llm_audit.jsonl", **kw)  # type: ignore[arg-type]
    return Run(tmp_path / "run", q.space, q, proposer, PairedBootstrapRule(resamples=500), cfg)


def history() -> History:
    return History(generation=1, feedback=(), archive=(CHAMP,))


def test_parse_clips_rounds_and_ignores_junk() -> None:
    text = 'noise {"params": {"a": 9, "k": 3.6, "zzz": 1, "b": true}} trailing'
    assert parse_params(text, CHAMP, SPACE) == {"a": 1.0, "k": 4.0}
    assert parse_params('{"a": "x", "k": NaN}', CHAMP, SPACE) == CHAMP.params
    for bad in ("no json here", '{"params": [1, 2]}', "{broken"):
        with pytest.raises(ValueError):
            parse_params(bad, CHAMP, SPACE)


def test_make_proposer_knows_llm() -> None:
    assert isinstance(make_proposer("llm", complete=FakeModel()), LLMProposer)


def test_prompts_never_contain_holdout_or_final_seeds(tmp_path: Path) -> None:
    model = FakeModel()
    run = run_with(tmp_path, model)
    run.run()
    assert model.prompts
    seeds = run.store.seeds()
    hidden = [int(s) for s in (*seeds["holdout"], *seeds["final"])]
    for prompt in model.prompts:
        numbers = {int(n) for n in re.findall(r"\d{4,}", prompt)}
        assert not numbers & set(hidden)
        assert "seed" not in prompt.lower()


def test_audit_has_one_line_per_call(tmp_path: Path) -> None:
    model = FakeModel()
    run_with(tmp_path, model).run()
    lines = (tmp_path / "llm_audit.jsonl").read_text().splitlines()
    assert len(lines) == len(model.prompts)
    first = json.loads(lines[0])
    assert {"prompt", "reply", "input_tokens", "output_tokens", "params"} <= first.keys()


def test_token_budget_stops_the_loop(tmp_path: Path) -> None:
    model = FakeModel(tokens=1000)
    run = run_with(tmp_path, model, generations=50, budget={"tokens": 2500})
    result = run.run()
    assert result.stop_reason == "token budget"
    assert len(model.prompts) == 2


def test_proposer_caps_its_own_spend() -> None:
    model = FakeModel(tokens=1000)
    p = LLMProposer(complete=model, max_dollars=0.001)
    rng = np.random.default_rng(0)
    p.propose(CHAMP, history(), SPACE, rng)
    second = p.propose(CHAMP, history(), SPACE, rng)
    assert len(model.prompts) == 1
    assert second.proposer == "llm"
    assert second.note.startswith("llm budget spent")
    assert p.spent()["dollars"] == pytest.approx((1000 * 4 + 500 * 20) / 1e6)


@pytest.mark.parametrize(
    ("model", "note"),
    [
        (FakeModel(fail=True), "llm call failed"),
        (FakeModel(refuse=True), "llm reply unusable: the model declined"),
    ],
)
def test_failures_fall_back_with_a_note(model: FakeModel, note: str, tmp_path: Path) -> None:
    p = LLMProposer(complete=model, audit_path=tmp_path / "a.jsonl")
    cand = p.propose(CHAMP, history(), SPACE, np.random.default_rng(0))
    assert cand.note.startswith(note)
    assert cand.proposer == "llm"
    assert p.failures == 1
    assert all(s.check(cand.params[s.name]) is None for s in SPACE)
    assert "error" in json.loads((tmp_path / "a.jsonl").read_text())


def test_state_round_trips() -> None:
    p = LLMProposer(complete=FakeModel())
    p.propose(CHAMP, history(), SPACE, np.random.default_rng(0))
    q = LLMProposer(complete=FakeModel())
    q.load_state(json.loads(json.dumps(p.state())))
    assert q.state() == p.state()
    assert q.calls == 1


def test_a_note_with_braces_after_the_json_does_not_spoil_the_reply() -> None:
    text = 'Here: {"params": {"a": 1.0}} (kept {k} as it was)'
    assert parse_params(text, CHAMP, SPACE)["a"] == 1.0
    assert parse_params('{not json} then {"a": 1.0}', CHAMP, SPACE)["a"] == 1.0


def test_openrouter_sends_a_chat_request_and_charges_the_reported_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arena.rsi.llm import OPENROUTER_URL, openrouter_complete

    sent: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def post(url: str, body: bytes, headers: dict[str, str]) -> object:
        sent.append((url, json.loads(body), dict(headers)))
        return {
            "choices": [{"message": {"content": '{"a": 1.0}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0042},
        }

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    complete = openrouter_complete("some/model", post=post)
    reply = complete("sys", "prompt")
    assert (reply.text, reply.input_tokens, reply.output_tokens) == ('{"a": 1.0}', 100, 20)
    assert reply.dollars == 0.0042 and not reply.refused
    url, body, headers = sent[0]
    assert url == OPENROUTER_URL and body["model"] == "some/model"
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "prompt"},
    ]
    assert body["reasoning"] == {"effort": "low"}
    assert headers["Authorization"] == "Bearer test-key"

    proposer = LLMProposer(complete=complete, provider="openrouter", max_dollars=1.0)
    history = History(1, (), (CHAMP,))
    cand = proposer.propose(CHAMP, history, SPACE, np.random.default_rng(0))
    assert cand.params["a"] == 1.0 and proposer.dollars == pytest.approx(0.0042)


def test_openrouter_without_a_key_or_with_an_error_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arena.rsi.llm import openrouter_complete

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        openrouter_complete("m", post=lambda *_: {})("s", "p")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    failing = openrouter_complete("m", post=lambda *_: {"error": {"message": "no credit"}})
    proposer = LLMProposer(complete=failing, provider="openrouter")
    cand = proposer.propose(CHAMP, History(1, (), (CHAMP,)), SPACE, np.random.default_rng(0))
    assert "llm call failed" in cand.note and proposer.failures == 1
    with pytest.raises(ValueError, match="unknown llm provider"):
        LLMProposer(provider="nope")
