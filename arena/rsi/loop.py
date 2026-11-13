"""The propose -> evaluate -> accept-or-reject -> archive loop (phase 3 spec, section 3).

Each generation the proposer suggests ``proposer.batch`` candidates, each is screened
against the champion on its own fresh dev slice, and only the best goes on to the
holdout seeds and the acceptance rule. The proposer then learns from ``Feedback`` that
holds dev results and the accept bit, never holdout data. Every random choice comes from
``rng_for(run_seed, generation, purpose)``, and proposer state is checkpointed after each
generation, so the same config replays to the same decisions, resumed or not.

With a ``SequentialRule`` (such as ``SequentialPairedRule``) both stages are staged: dev
seeds are played in chunks and a candidate that is clearly worse (or clearly better)
stops early, and holdout seeds are played up to the rule's planned looks, stopping at the
first look that decides. The seeds and their order are the same as an unstaged run's;
only how many get played changes. Any other rule runs exactly as before.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from arena.rsi.accept import bootstrap_ci
from arena.rsi.report import write_report
from arena.rsi.seeds import SeedPools, rng_for
from arena.rsi.store import RunStore
from arena.rsi.types import (
    AcceptanceRule,
    Budget,
    Candidate,
    Decision,
    Evaluator,
    Feedback,
    History,
    PairedResult,
    ParamSpec,
    Proposer,
    SequentialRule,
    defaults,
    validate,
)


@dataclass(frozen=True)
class RunConfig:
    run_seed: int = 0
    problem: str = "problem"
    dev_pairs: int = 100
    holdout_pairs: int = 100
    holdout_rotate: int = 10
    holdout_blocks: int = 10
    dev_pool: int = 10_000
    final_pairs: int = 200
    patience: int | None = None
    budget: Budget = field(default_factory=Budget)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["budget"] = self.budget.to_dict()
        return d


@dataclass(frozen=True)
class Pending:
    """One computed but not yet committed generation of a run."""

    generation: int
    champion: Candidate
    record: dict[str, Any]
    state: dict[str, Any]
    feedback: list[Feedback]


@dataclass
class RunResult:
    champion: Candidate
    baseline: Candidate
    generations: int
    accepted: int
    stop_reason: str
    final: dict[str, Any] | None


def _result_to_dict(r: PairedResult) -> dict[str, Any]:
    return {
        "seeds": list(r.seeds),
        "score_cand": list(r.score_a),
        "score_champ": list(r.score_b),
        "failures": r.failures,
        "guards": {k: list(v) for k, v in r.guards().items()},
    }


def _result_from_dict(d: Mapping[str, Any]) -> PairedResult:
    guards = d.get("guards") or {}
    return PairedResult(
        tuple(d["seeds"]),
        tuple(d["score_cand"]),
        tuple(d["score_champ"]),
        {"guards": {k: tuple(v) for k, v in guards.items()}} if guards else {},
        d["failures"],
    )


class Run:
    """One improvement run in ``run_dir``; calling ``run()`` again resumes it."""

    def __init__(
        self,
        run_dir: str | Path,
        space: Sequence[ParamSpec],
        evaluator: Evaluator,
        proposer: Proposer,
        rule: AcceptanceRule,
        config: RunConfig,
        baseline: Mapping[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = RunStore(Path(run_dir))
        self.space = tuple(space)
        self.evaluator = evaluator
        self.proposer = proposer
        self.rule = rule
        self.config = config
        self.clock = clock
        params = dict(baseline) if baseline is not None else defaults(self.space)
        problems = validate(params, self.space)
        if problems:
            raise ValueError(f"invalid baseline: {'; '.join(problems)}")
        self.baseline = Candidate.make(params, None, 0, "baseline", "generation-0 baseline")

    # -- setup and resume ---------------------------------------------------------

    def _identity(self) -> dict[str, Any]:
        return {
            "config": {k: v for k, v in self.config.to_dict().items() if k != "budget"},
            "space": [asdict(p) for p in self.space],
            "proposer": self.proposer.name,
            "rule": self.rule.to_dict(),
            "baseline": self.baseline.to_dict(),
        }

    def _open(self) -> tuple[SeedPools, dict[str, Any]]:
        c = self.config
        if self.store.exists() and self.store.checkpoint() is not None:
            stored = self.store.config()
            if stored["identity"] != self._identity():
                raise ValueError(
                    f"{self.store.dir} holds a different run; only the budget may change on resume"
                )
            pools = SeedPools.from_dict(self.store.seeds())
            state = self.store.checkpoint()
            assert state is not None
            self.store.truncate_records(state["generation"])
            self.store.archive.load(state["archive"])
            self.proposer.load_state(state["proposer"])
            return pools, state
        pools = SeedPools.generate(
            c.run_seed,
            c.dev_pool,
            c.dev_pairs,
            c.holdout_pairs,
            c.holdout_blocks,
            c.holdout_rotate,
            c.final_pairs,
        )
        self.store.create(
            {"identity": self._identity(), "budget": c.budget.to_dict()}, pools.to_dict()
        )
        self.store.archive.add(self.baseline)
        state = {
            "generation": 0,
            "champion": self.baseline.id,
            "archive": [self.baseline.id],
            "proposer": self.proposer.state(),
            "rejected": [],
            "episodes": 0,
            "since_accept": 0,
            "accepted": 0,
            "seconds": 0.0,
            "stop_reason": None,
        }
        self.store.save_checkpoint(state, self.baseline)
        return pools, state

    def _feedback(self) -> list[Feedback]:
        out = []
        for rec in self.store.records():
            for f in rec["feedback"]:
                dev = _result_from_dict(f["dev"]) if f["dev"] is not None else None
                out.append(
                    Feedback(
                        rec["generation"],
                        Candidate.from_dict(f["candidate"]),
                        f["accepted"],
                        f["stage"],
                        dev,
                    )
                )
        return out

    # -- one generation -------------------------------------------------------------

    def _evaluate(self, a: Candidate, b: Candidate, seeds: Sequence[int]) -> PairedResult:
        try:
            return self.evaluator.evaluate(a, b, seeds)
        except Exception as e:  # a crashing candidate is a failed candidate
            zeros = (0.0,) * len(seeds)
            return PairedResult(tuple(seeds), zeros, zeros, {"error": repr(e)}, len(seeds))

    def _stop_reason(self, state: Mapping[str, Any]) -> str | None:
        b, c = self.config.budget, self.config
        if (self.store.dir / "STOP").exists():
            return "stop file"
        if b.generations is not None and state["generation"] >= b.generations:
            return "generation budget"
        if b.episodes is not None and state["episodes"] >= b.episodes:
            return "episode budget"
        if b.seconds is not None and state["seconds"] >= b.seconds:
            return "time budget"
        spent = getattr(self.proposer, "spent", None)
        if callable(spent):
            used = spent()
            if b.tokens is not None and used.get("tokens", 0) >= b.tokens:
                return "token budget"
            if b.dollars is not None and used.get("dollars", 0.0) >= b.dollars:
                return "dollar budget"
        if c.patience is not None and state["since_accept"] >= c.patience:
            return f"no accept in {c.patience} generations"
        return None

    def _staged_dev(
        self,
        rule: SequentialRule,
        cand: Candidate,
        champion: Candidate,
        seeds: Sequence[int],
        state: dict[str, Any],
    ) -> tuple[PairedResult, str | None]:
        """Dev in chunks, stopping when the rule says the candidate is clearly worse or
        clearly better (racing). Returns the dev result so far and the rule's verdict."""
        dev: PairedResult | None = None
        verdict: str | None = None
        done = 0
        for n in rule.dev_looks(len(seeds)):
            part = self._evaluate(cand, champion, seeds[done:n])
            state["episodes"] += 2 * part.n
            dev = part if dev is None else dev.extend(part)
            done = n
            verdict = rule.dev_interim(dev)
            if verdict is not None:
                break
        assert dev is not None
        return dev, verdict

    def _staged_holdout(
        self,
        rule: SequentialRule,
        cand: Candidate,
        champion: Candidate,
        dev: PairedResult,
        g: int,
        pools: SeedPools,
        state: dict[str, Any],
    ) -> Decision:
        """Holdout at the rule's planned looks over the decision plus extension seeds."""
        seeds, extra = pools.holdout_block(g)
        sample = seeds + extra
        looks = rule.holdout_looks(len(seeds), len(extra))
        rng = rng_for(self.config.run_seed, g, "bootstrap")
        holdout: PairedResult | None = None
        done = 0
        for n in looks:
            part = self._evaluate(cand, champion, sample[done:n])
            state["episodes"] += 2 * part.n
            holdout = part if holdout is None else holdout.extend(part)
            done = n
            decision = rule.decide_at(dev, holdout, looks, rng)
            if decision is not None:
                return decision
        raise AssertionError("a sequential rule must decide at its last look")

    def _generation(
        self,
        g: int,
        pools: SeedPools,
        state: dict[str, Any],
        champion: Candidate,
        feedback: list[Feedback],
    ) -> tuple[Candidate, dict[str, Any]]:
        seed = self.config.run_seed
        history = History(g, tuple(feedback), tuple(self.store.archive.members))
        rng = rng_for(seed, g, "propose")
        rejected = set(state["rejected"])
        entries: list[dict[str, Any]] = []
        screened: list[tuple[Candidate, PairedResult, int]] = []
        invalid: list[tuple[Candidate, str]] = []
        staged = self.rule if isinstance(self.rule, SequentialRule) else None
        stopped: set[str] = set()
        for i in range(self.proposer.batch):
            cand = self.proposer.propose(champion, history, self.space, rng)
            problems = validate(cand.params, self.space)
            if cand.id == champion.id:
                problems.append("same as the champion")
            elif cand.id in rejected:
                problems.append("already rejected")
            elif any(c.id == cand.id for c, _, _ in screened):
                problems.append("duplicate in this generation")
            if problems:
                invalid.append((cand, "; ".join(problems)))
                continue
            dev_seeds = pools.dev_slice(seed, g, i)
            if staged is None:
                dev = self._evaluate(cand, champion, dev_seeds)
                state["episodes"] += 2 * dev.n
            else:
                dev, verdict = self._staged_dev(staged, cand, champion, dev_seeds, state)
                if verdict == "stop":
                    stopped.add(cand.id)
            screened.append((cand, dev, i))

        best: tuple[Candidate, PairedResult, int] | None = None
        live = [t for t in screened if t[0].id not in stopped] or screened
        if live:
            best = max(live, key=lambda t: (t[1].failures == 0, t[1].mean_diff, -t[2]))
        if best is None:
            why = "; ".join(f"{c.id}: {p}" for c, p in invalid) or "no candidate proposed"
            decision = Decision(False, "validate", f"no valid candidate ({why})")
        else:
            cand, dev, _ = best
            early = self.rule.passes_dev(dev)
            if early is None and cand.id in stopped:
                why = f"stopped early on dev after {dev.n} pairs (mean {dev.mean_diff:+.4g})"
                early = Decision(False, "dev", why, {"dev": dev.summary()})
            if early is not None:
                decision = early
            elif staged is not None:
                decision = self._staged_holdout(staged, cand, champion, dev, g, pools, state)
            else:
                seeds, extra = pools.holdout_block(g)
                holdout = self._evaluate(cand, champion, seeds)
                state["episodes"] += 2 * holdout.n
                extended = False
                if self.rule.wants_extension(holdout, rng_for(seed, g, "extension")):
                    more = self._evaluate(cand, champion, extra)
                    state["episodes"] += 2 * more.n
                    holdout, extended = holdout.extend(more), True
                decision = self.rule.decide(dev, holdout, rng_for(seed, g, "bootstrap"), extended)

        fb: list[Feedback] = [Feedback(g, c, False, "validate", None) for c, _ in invalid]
        for cand, dev, _ in screened:
            if best is not None and cand.id == best[0].id:
                stage: Literal["dev", "holdout"] = "dev" if decision.stage == "dev" else "holdout"
                fb.append(Feedback(g, cand, decision.accept, stage, dev))
            else:
                fb.append(Feedback(g, cand, False, "screened", dev))
        for f in fb:
            entries.append(
                {
                    "candidate": f.candidate.to_dict(),
                    "accepted": f.accepted,
                    "stage": f.stage,
                    "dev": _result_to_dict(f.dev) if f.dev is not None else None,
                    "problem": next((p for c, p in invalid if c.id == f.candidate.id), None),
                }
            )
            if not f.accepted and f.candidate.id != champion.id:
                rejected.add(f.candidate.id)

        if decision.accept and best is not None:
            champion = best[0]
            state["accepted"] += 1
            state["since_accept"] = 0
        else:
            state["since_accept"] += 1
        self.proposer.observe(fb)
        feedback.extend(fb)
        state["rejected"] = sorted(rejected)
        record = {
            "generation": g,
            "champion_before": state["champion"],
            "chosen": best[0].id if best else None,
            "decision": decision.to_dict(),
            "champion_after": champion.id,
            "episodes": state["episodes"],
            "feedback": entries,
        }
        return champion, record

    # -- stepping, for drivers that run several lineages in lockstep -----------------

    def open(self) -> None:
        """Create or resume the run directory; ``step``/``commit``/``finish`` need it."""
        self._pools, self._state = self._open()
        self._champion = next(
            m for m in self.store.archive.members if m.id == self._state["champion"]
        )
        self._history = self._feedback()
        self._started, self._seconds0 = self.clock(), self._state["seconds"]
        self._state["stop_reason"] = None

    @property
    def generation(self) -> int:
        return int(self._state["generation"])

    @property
    def champion(self) -> Candidate:
        return self._champion

    @property
    def state(self) -> Mapping[str, Any]:
        return self._state

    def stop_reason(self) -> str | None:
        return self._stop_reason(self._state)

    def step(self, g: int) -> Pending:
        """Run generation ``g`` without writing anything; ``commit`` makes it stick.

        The proposer's in-memory state moves on, but its checkpoint does not, so a crash
        before ``commit`` resumes from the last committed generation.
        """
        state = dict(self._state)
        feedback = list(self._history)
        champion, record = self._generation(g, self._pools, state, self._champion, feedback)
        state["generation"] = g
        state["champion"] = champion.id
        members = [m.id for m in self.store.archive.members]
        state["archive"] = members + ([champion.id] if champion.id not in members else [])
        state["proposer"] = self.proposer.state()
        state["seconds"] = self._seconds0 + self.clock() - self._started
        return Pending(g, champion, record, state, feedback)

    def commit(self, pending: Pending) -> None:
        if all(m.id != pending.champion.id for m in self.store.archive.members):
            self.store.archive.add(pending.champion)
        self.store.append_record(pending.record)
        self.store.save_checkpoint(pending.state, pending.champion)
        self._state, self._champion = pending.state, pending.champion
        self._history = pending.feedback

    def finish(self, reason: str) -> RunResult:
        """Record why the run stopped, check the champion on final seeds, write the report."""
        state = self._state
        state["stop_reason"] = reason
        self.store.save_checkpoint(state, self._champion)
        final = self._final(self._pools, self._champion)
        result = RunResult(
            self._champion, self.baseline, state["generation"], state["accepted"], reason, final
        )
        write_report(self.store, result, self.space)
        return result

    # -- the run ------------------------------------------------------------------

    def run(self, on_generation: Callable[[dict[str, Any]], None] | None = None) -> RunResult:
        self.open()
        while (reason := self.stop_reason()) is None:
            pending = self.step(self.generation + 1)
            self.commit(pending)
            if on_generation is not None:
                on_generation(pending.record)
        return self.finish(reason)

    def _final(self, pools: SeedPools, champion: Candidate) -> dict[str, Any] | None:
        """Champion vs baseline on the final seeds, which nothing saw during the run."""
        if champion.id == self.baseline.id:
            return None
        r = self._evaluate(champion, self.baseline, pools.final)
        lo, hi = bootstrap_ci(r.diffs, rng_for(self.config.run_seed, 0, "final"))
        return {
            **r.summary(),
            "ci": [lo, hi],
            "guards": {k: list(v) for k, v in r.guards().items()},
        }
