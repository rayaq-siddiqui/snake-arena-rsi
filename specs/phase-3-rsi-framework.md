# Phase 3 — The Generic RSI Framework

**Goal:** build a reusable *propose → evaluate → accept-or-reject → archive* loop that
can improve **anything** described by a parameter set and a scoring function. It must not
import or know about snakes. Phase 4 plugs each snake into it.

Read [`rsi/`](rsi/README.md) first for the ideas behind this design.

## 1. What "recursive" means here (and what it doesn't)

The loop is recursive in two honest, bounded ways:

1. **The output feeds the input.** Each accepted improvement becomes the new starting
   point *and* a future opponent, so the problem a snake is solving keeps changing
   because its rivals improved too (co-evolution).
2. **The improver improves its own search settings.** The proposer adapts its own
   hyperparameters (mutation step size, which parameters to touch) from the record of
   which proposals were accepted. Optionally (a stretch step in `plan.md`), a "meta" run uses the framework to
   tune the proposer's settings on a benchmark.

It does **not** rewrite its own evaluator, acceptance rule or tests, and it does not
change any language model. That limit is deliberate: an improver that can edit its own
grading can always "improve" by grading itself more kindly.

## 2. Core types (`arena/rsi/`, standard library + NumPy only)

```python
@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: Literal["float", "int"]
    low: float
    high: float
    default: float
    scale: Literal["linear", "log"] = "linear"

@dataclass(frozen=True)
class Candidate:
    id: str                       # content hash of params
    params: Mapping[str, float]
    parent_id: str | None
    generation: int
    proposer: str                 # which proposer made it
    note: str                     # human-readable "what changed"

class Proposer(Protocol):
    name: str
    def propose(self, champion: Candidate, history: History,
                space: Sequence[ParamSpec], rng: np.random.Generator) -> Candidate: ...
    def observe(self, decision: Decision) -> None: ...   # learn from accept/reject

class Evaluator(Protocol):
    def evaluate(self, a: Candidate, b: Candidate,
                 seeds: Sequence[int]) -> PairedResult: ...
    # Runs a and b on the SAME seeds and returns one score per seed for each.

@dataclass(frozen=True)
class PairedResult:
    seeds: tuple[int, ...]
    score_a: tuple[float, ...]
    score_b: tuple[float, ...]
    diagnostics: Mapping[str, Any]   # secondary metrics, never used to grade unless declared
    failures: int                    # crashes/timeouts of the candidate

class AcceptanceRule(Protocol):
    def decide(self, dev: PairedResult, holdout: PairedResult | None) -> Decision: ...
```

The framework talks to the outside world only through `ParamSpec`, `Evaluator` and the
problem's `seeds`. Anything that can provide those can be improved.

## 3. The loop

```
for generation in 1..G:
    freeze champion; snapshot config, seeds, code hash
    candidate  = proposer.propose(champion, history, space, rng)
    validate   candidate (bounds, types, hash not already rejected)
    dev        = evaluator.evaluate(candidate, champion, dev_seeds[generation])
    if not rule.passes_dev(dev):          reject, record why, continue
    holdout    = evaluator.evaluate(candidate, champion, holdout_seeds)
    decision   = rule.decide(dev, holdout)
    if decision.accept: champion = candidate; archive.add(candidate)
    proposer.observe(decision)
    write generation record; checkpoint
    stop if budget exhausted or no improvement for `patience` generations
```

- **Proposals per generation:** default 1; a proposer may evaluate up to `k` candidates on
  dev seeds and send only its best to holdout (costs `k×` dev matches; counted in the
  budget).
- **Determinism:** every random choice uses a `numpy.random.Generator` seeded from
  `(run_seed, generation, purpose)`. The same run config replays to the same decisions.
- **Resume:** each generation is written atomically; restarting continues from the last
  committed generation with identical results.

## 4. Seeds: three pools that never mix

| Pool | Used for | Who sees it |
|---|---|---|
| **dev** | Screening each candidate. A fresh slice per generation, drawn from a large pool. | Proposer may see dev results |
| **holdout** | The accept/reject decision | Only the acceptance rule. Never the proposer. |
| **final** | End-of-run reporting only | Nobody during the run |

Seed pools are generated once from a run seed and stored in the run directory. The
holdout pool is rotated every `holdout_rotate` generations so the loop can't slowly
overfit to it by many small accepted steps.

## 5. Acceptance rule (default: `PairedBootstrapRule`)

A candidate is accepted only if **all** of these hold:

1. Zero failures (crashes, timeouts, invalid output) in all evaluation games.
2. Dev screen: mean paired difference `mean(score_cand − score_champ) > 0`.
3. Holdout: relative improvement of the mean ≥ `min_rel_gain` (default **+2%**).
4. Holdout: the 95% **paired bootstrap** confidence interval of the mean difference
   (10,000 resamples, seeded) lies entirely above 0.
5. Guard-rails: no declared guard metric gets worse by more than its tolerance (for
   example "deaths per 1,000 ticks may not rise more than 15%").

Defaults: 100 dev pairs, 100 holdout pairs. If the interval straddles zero but the mean
looks promising, the rule may request one extension (another 100 holdout pairs) before
deciding; that is the only adaptive sampling allowed, and it's logged.

Every decision records: means, difference, interval, sample sizes, guard metrics, and a
one-line rationale.

## 6. Built-in proposers

All operate in a normalised `[0, 1]` space per parameter (log scale where declared), then
map back and clip to bounds.

| Proposer | Idea | Self-adaptation |
|---|---|---|
| `RandomRestart` | Sample a fresh point uniformly. The control: any real method must beat it. | none |
| `GaussianHillClimb` | Perturb 1–3 random parameters with N(0, σ) | **1/5th success rule:** σ grows ×1.5 after an accept, shrinks ×0.9 after a reject, within `[σ_min, σ_max]` |
| `CoordinateSearch` | Try +δ / −δ on one parameter at a time, cycling | δ halves after a full cycle with no accept |
| `CrossEntropy` | Keep a Gaussian over parameters; sample `k` on dev, refit to the best few | mean and spread update every generation |
| `ArchiveCrossover` | Mix parameters of two archive members, then mutate lightly | parent choice favours members that beat more opponents |
| `LLMProposer` *(optional, off by default)* | Show an LLM the param schema and dev diagnostics, ask for a new param set + rationale | none; budgeted by tokens and cost |

The `LLMProposer` only ever returns **numbers within declared bounds** — never code — so
its output can't execute anything. It never sees holdout or final seeds. A separate,
later "code proposer" that edits strategy source is out of scope until a real sandbox
exists (container/microVM, no network, read-only engine, capped CPU/memory, no
credentials); until then any code it produces is **review-only**.

## 7. Hall of fame and opponents

- The archive (hall of fame) stores every accepted candidate immutably, plus the
  generation-0 baseline. Entries are never edited or deleted.
- Evaluators can ask the archive for opponents: `latest`, `baseline`, `uniform over
  archive`, or `milestones` (every Nth champion). This is how phase 4 stops a lineage
  overfitting to today's rivals.

## 8. Budgets and stopping

A `Budget` caps: generations, total evaluation episodes, wall-clock time, and (for
`LLMProposer`) tokens and dollars. The loop stops cleanly when any cap is hit, when
`patience` generations pass without an accept, or on a manual stop file
(`run_dir/STOP`). Stopping always leaves a valid, resumable checkpoint.

## 9. Storage (per run directory)

```
runs/<run-id>/
  config.json            run config + framework version + code hash
  seeds.json             dev / holdout / final pools
  generations.jsonl      one record per generation (candidate, results, decision)
  archive/<cand-id>.json immutable accepted candidates
  champion.json          pointer to the current champion
  report.md              human summary written at the end
```

## 10. Proving the framework works without snakes

Before any snake uses it, the framework is tested on toy problems in `tests/rsi/`:

- **Noisy quadratic:** score = −‖x − x*‖² + noise. The loop must move toward `x*`,
  and must reject candidates whose true score is worse at least 95% of the time.
- **Pure noise:** every candidate has the same true score. The rule must accept almost
  nothing (false-accept rate ≤ 5% over 200 generations). This is the test that catches
  "improvement" that is really luck.
- **Rigged evaluator:** an evaluator that crashes on some candidates — they must never
  be accepted.
- **Determinism and resume:** the same run config gives the same decisions; killing and
  resuming mid-run gives the same result as an uninterrupted run.
- **Isolation:** the proposer object never receives holdout seeds or holdout results
  (asserted by a spy evaluator).

## 11. Acceptance criteria

- `arena/rsi` has no import from `arena.engine`, `arena.agents` or `arena.sim` (checked by
  a test that walks the imports).
- All toy-problem tests in §10 pass.
- On the noisy quadratic in 5 dimensions, `GaussianHillClimb` reaches within 10% of the
  optimum's score in ≤ 60 generations on ≥ 9 of 10 run seeds, and beats `RandomRestart`
  on the same budget.
- `python -m arena.cli rsi-demo --problem quadratic` runs a full loop and writes a run
  directory with the layout in §9.
