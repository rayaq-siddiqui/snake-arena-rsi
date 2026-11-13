# Build Plan

The ordered build queue for Snake Arena RSI. Work top to bottom. Each step is sized to
land as **one to three small commits**, has concrete **targets**, and ends with a
**Done when** check that must pass before the next step starts.

- Specs are the contract: [phase 1](phase-1-arena.md), [phase 2](phase-2-personalities.md),
  [phase 3](phase-3-rsi-framework.md), [phase 4](phase-4-snake-rsi.md).
- Background: [RSI course](rsi/README.md).
- Tick the box and add the commit hash when a step lands. If a target proves wrong,
  change it here **and** in the spec in the same commit, and say why.
- Never claim a number you didn't measure. Record measured numbers in the
  **Measurements** table at the bottom.

**Legend:** `[ ]` todo · `[~]` in progress · `[x]` done

---

## Step 0 — Scaffold

### 0.1 Python project `[x]`
- `pyproject.toml` (Python ≥ 3.12, managed with `uv`), package `arena/` with empty
  subpackages `engine`, `agents`, `sim`, `rsi`, `evolution`, `viz`.
- Dev tools: `pytest`, `hypothesis`, `ruff` (lint + format), `mypy --strict` on `arena/`.
- Runtime deps: none so far (standard library only). `numpy` arrives with phase 3 and
  `matplotlib` with reports in step 4.4.
- **Targets:** `uv sync && uv run pytest` passes on a clean clone (one smoke test);
  `uv run ruff check . && uv run ruff format --check . && uv run mypy arena` are clean.
- **Done when:** the commands above pass and are documented in `AGENTS.md`.

### 0.2 CLI skeleton `[x]`
- `arena/cli.py` with `argparse` subcommands. *As built:* `run-match`, `run-tournament`,
  `bench` and `watch` exist; `rsi-demo`, `evolve` and `report` are added by the steps that
  implement them rather than as stubs.
- **Targets:** `python -m arena.cli --help` lists all subcommands.

### 0.3 CI `[x]`
- `.github/workflows/ci.yml`: on push to `main`, run ruff, mypy and pytest on Python 3.12
  and 3.13.
- **Done when:** the first push shows a green run.

---

## Step 1 — The arena (phase 1)

### 1.1 Core types `[x]`
- `arena/engine/types.py`: `Cell`, `Direction`, `SnakeId`, `GameConfig`, `SnakeState`,
  `GameState`, all events (`Death`, `Kill`, `Spawn`, `ActionFallback`, `MatchEnd`),
  `SnakeView`, `Observation`. Frozen dataclasses; tuples not lists.
- `GameConfig` validates ranges (length 3–10, board ≥ 10 × 10, five snakes).
- **Targets:** every type round-trips through `to_dict`/`from_dict` (tested).

### 1.2 Seeded RNG `[x]`
- `arena/engine/rng.py`: a small explicit RNG state stored inside `GameState`
  (*as built:* SplitMix64, one integer); helper to derive child seeds from
  `(match_seed, purpose, snake_id)`.
- **Targets:** same seed ⇒ same sequence; different purposes ⇒ independent streams;
  state is JSON-serialisable.

### 1.3 Movement and collisions `[x]`
- `arena/engine/step.py`: `step(state, actions) -> (state, events)` implementing phase 1
  §2 exactly: reversal handling, tail removal snapshot, wall / self / body / head-on /
  head-swap, simultaneous kill credit, multi-victim credit, commit.
- **Targets:** one golden test per bullet in phase 1 §11 "Wall" through "Tail race" —
  each a hand-drawn small board (e.g. 8 × 8) with expected events.
- **Done when:** all golden tests pass, and a test proves results don't depend on the
  order snakes are listed in.

### 1.4 Spawning and respawn `[x]`
- `arena/engine/spawn.py`: seeded attempts (100) + deterministic row-major fallback,
  clearance rules, new `life_id`s, 10-tick respawn counter, retry when full.
- **Targets:** golden tests for respawn timing, score persistence, no-room retry on a
  crowded tiny board; property test: no spawn ever overlaps a living snake.

### 1.5 Match end and ranking `[x]`
- Win at `score_target`, end at `max_ticks`, ranking by kills → deaths → alive ticks →
  shared rank.
- **Targets:** tests for single winner, simultaneous crossers, tick-cap end, full ties.

### 1.6 Invariant fuzzing `[x]`
- `tests/engine/test_invariants.py` with `hypothesis` + a `RandomUniform` driver:
  shape invariant, one-cell moves, no reversals, scores == count of `Kill` events.
- **Targets:** 200 seeds × 2,000 ticks run in < 60 s in CI.
- **Done when:** M1 of the vision is satisfied: golden tests + invariants pass.

### 1.7 Policies and the match runner `[x]`
- `arena/agents/base.py` (`Policy` protocol, per-policy seeded RNG),
  `arena/agents/random_policies.py` (`RandomUniform`, `RandomSafe`).
- `arena/sim/match.py`: `simulate_match(policies, seed, config, record=False) ->
  MatchResult`; builds observations, applies a per-move time budget (fallback +
  `ActionFallback` event on error/timeout), optional replay recording.
- **Targets:** determinism test (same seed twice ⇒ identical events);
  a policy that raises gets the fallback and the match continues.

### 1.8 Replays `[x]`
- `arena/sim/replay.py`: write/read the phase 1 §8 schema; `resimulate(replay)`
  reproduces events from stored actions with no policies.
- **Targets:** round-trip test on 20 seeds; schema version checked on load.
- *As built:* each snake's policy is stored with a source hash, and verification also
  recounts kills and deaths from the stored events and checks them against the standings.

### 1.9 Headless CLIs `[x]`
- `run-match` (prints standings table, optional `--replay`), `run-tournament` (process
  pool, JSONL per match, summary CSV, 5 × 5 kill matrix).
- **Targets:** `run-tournament --matches 100` with `RandomSafe` gives byte-identical
  summaries with `--workers 1` and `--workers 4`.

### 1.10 Benchmark `[x]`
- `bench` subcommand: ticks/second for the engine alone and with policies; kills per
  1,000 ticks for `RandomSafe` on 100 × 100.
- **Targets:** ≥ 20,000 engine ticks/s single process (phase 1 §10). If missed, profile,
  fix the top hotspot once, and record the real number either way.

### 1.11 Visualization `[x]`
- `arena/viz/server.py` (stdlib `http.server`; *as built:* the page pulls frames in
  chunks instead of SSE, so pause/speed stay client-side) and `arena/viz/static/index.html`
  (Canvas + vanilla JS): board, five colours, head markers, interpolation, leaderboard,
  kill feed, play/pause/step/speed/restart/new seed; replay mode loads a JSON file.
- **Targets:** `watch --seed 42` shows a live match; a Playwright smoke test loads the
  page, sees five snakes, presses pause and checks the tick counter stops; a test checks
  the viewer's final standings equal `run-match --seed 42` for a short match.
- *As built:* the viewer defaults to 20 × 20 and first to 10 kills, with a settings form
  for every game parameter, "finish now", and replay download/upload.
- **Done when:** phase 1 acceptance (§11) passes in full; README updated with the real
  commands, the benchmark number and a screenshot.
- *Status:* done. Every §11 check has an automated test (golden collision boards,
  20 × 10,000-tick invariant matches with per-spawn safety checks, simultaneous target
  crossers, replay and determinism tests); README has the commands, measured speed and
  the viewer screenshot.

---

## Step 2 — Personalities (phase 2)

### 2.1 Feature library `[x]`
- `arena/agents/features.py`: every feature in phase 2 §1, each a pure function with its
  own unit tests on hand-built boards; flood fill bounded by `space_cap` and radius.
- **Targets:** each feature < 0.3 ms median on a 100 × 100 board.
- *As built:* adds `territory` (a head-start race against enemy heads) and the
  `keep_distance` / `keep_repel` / `pull_radius` shape parameters for
  `nearest_enemy_head`; phase 2 spec §1 says why. Slowest median is `territory` at
  0.041 ms (p99 0.15 ms); timed by a script, not a test, since tests never depend on
  wall-clock time.

### 2.2 Param spaces and scorer `[x]`
- `arena/agents/params.py` (`ParamSpace`, JSON load/save with bounds checks) and
  `arena/agents/scorer.py` (weighted-sum move choice, fixed tie-break order).
- `arena/agents/params/<name>.json` for all five, version 1.
- **Targets:** out-of-bounds or unknown params are rejected with a clear error.

### 2.3 Hunter, Survivor, Trapper `[x]`
- One module each; default weights hand-set.
- **Targets:** each beats `RandomSafe` on kills/1,000 ticks in a 30-match smoke
  tournament (full check in 2.6).
- *Status:* met; `check-personalities --matches 30` passed every phase 2 §5 check.

### 2.4 Predictor `[x]`
- Opponent next-head probability map, `lookahead` (default 2) expected-value scoring.
- **Targets:** p99 decision time ≤ 20 ms on 100 × 100.
- *Status:* met; p99 1.95 ms (`bench --policies all`).

### 2.5 Opportunist `[x]`
- Cruise / attack weight sets switched by `attack_threshold`.
- **Targets:** unit test showing the switch flips when an enemy is boxed in.

### 2.6 Personality tournament and metrics `[x]`
- Tournament runner reports behaviour metrics (phase 2 §3); viewer shows names/colours.
- **Targets:** all phase 2 §5 acceptance criteria, measured on 100 matches; behaviour
  table recorded under Measurements.
- **Density check:** record mean ticks to first-to-100 with all five personalities. If
  > 50,000, record it and add an explicitly labelled `experiment` board config (e.g.
  50 × 50) for phase 4 runs. Defaults stay unchanged.
- **Done when:** phase 2 acceptance passes.
- *As built:* `check-personalities` runs every §5 tournament and check and exits
  non-zero on a failure; `bench --policies all` checks the decision budget. The viewer
  opens on the `personalities` lineup with names and colours.
- *Status:* done. The 100-match report, all checks passing, is in
  `docs/phase-2-check.md`. Density check: first-to-100 is never reached (see
  Measurements), so `arena/sim/boards.py` adds a labelled 50 × 50 `experiment` board;
  phase 4 decides whether to use it.

Behaviour table (100 matches, all five together, 5,000-tick episodes on 100 × 100):

| personality | kills/1k alive | deaths/1k alive | enemy distance | reachable space | kills/1k vs 4 × RandomSafe (95% CI of advantage) |
|---|---|---|---|---|---|
| Hunter | 0.008 | 0.018 | **4.9** (lowest) | 73.3 | 1.658 (+1.53 … +1.76) |
| Survivor | 0.000 | **0.000** (fewest) | 6.7 | **76.3** (highest) | 0.242 (+0.18 … +0.29) |
| Trapper | 0.002 | 0.010 | 14.5 | 68.7 | 0.762 (+0.66 … +0.84) |
| Predictor | 0.024 | 0.004 | 15.6 | 68.6 | 1.730 (+1.60 … +1.82) |
| Opportunist | 0.000 | 0.034 | 10.5 | 68.9 | 0.150 (+0.11 … +0.18) |
| RandomSafe ×5 (baseline) | 0.009 | 0.192 | 35.9 | 77.5 | — |

---

## Step 3 — Generic RSI framework (phase 3)

### 3.1 Types and storage `[x]`
- `arena/rsi/types.py` (`ParamSpec`, `Candidate`, `PairedResult`, `Decision`,
  `History`, `Budget`), `arena/rsi/store.py` (run directory layout, atomic writes,
  `generations.jsonl`, immutable archive).
- **Targets:** an import-graph test proves `arena.rsi` imports nothing from
  `arena.engine`, `arena.agents`, `arena.sim`.
  *As built:* `Feedback` added (what proposers may see); `store.py` also holds the `Archive` with
  opponent sampling (`latest`/`baseline`/`uniform`/`milestones`). `tests/rsi/test_imports.py`
  walks the AST.

### 3.2 Seed pools `[x]`
- `arena/rsi/seeds.py`: dev / holdout / final pools from a run seed, per-generation dev
  slices, holdout rotation.
- **Targets:** pools are disjoint (tested); same run seed ⇒ same pools.
  *As built:* pools drawn without repeats; holdout blocks hold the sample plus its one
  extension; `tests/rsi/test_seeds.py`.

### 3.3 Acceptance rule `[x]`
- `arena/rsi/accept.py`: `PairedBootstrapRule` with dev screen, min relative gain,
  seeded bootstrap CI, guard metrics, one optional extension, rationale text.
- **Targets:** unit tests on fixed arrays (accept, reject on CI, reject on gain, reject on
  guard, reject on failures, extension path).
  *As built:* `tests/rsi/test_accept.py` covers every path listed.

### 3.4 Proposers `[x]`
- `arena/rsi/proposers.py`: `RandomRestart`, `GaussianHillClimb` (1/5th rule),
  `CoordinateSearch`, `CrossEntropy`, `ArchiveCrossover`; normalised/log space mapping.
- **Targets:** every proposal is within bounds (property test); proposer state
  round-trips through the checkpoint.
  *As built:* proposers learn from `Feedback` (dev results + accept bit), never a
  `Decision`; a `batch` attribute lets `CrossEntropy` screen 6 per generation.

### 3.5 The loop, budgets and resume `[x]`
- `arena/rsi/loop.py`: phase 3 §3 loop, budgets, patience, STOP file, checkpoint/resume.
- **Targets:** kill-and-resume test equals an uninterrupted run; same config ⇒ identical
  `generations.jsonl`.
  *As built:* kill-resume tested after 1, 7 and 16 generations plus a half-written
  line; a fake clock tests the time budget.

### 3.6 Toy problems and demo `[x]`
- `arena/rsi/toys.py`: noisy quadratic, pure noise, crashing evaluator; spy evaluator
  asserting the proposer never sees holdout data; `rsi-demo` CLI.
- **Targets (phase 3 §11):** quadratic within 10% in ≤ 60 generations on ≥ 9/10 seeds and
  beats `RandomRestart`; pure-noise false-accept rate ≤ 5% over 200 generations; crashing
  candidates never accepted.
- **Done when:** phase 3 acceptance passes.
  *As built:* "within 10%" means remaining regret ≤ 10% of the baseline's (the
  optimum scores 0). Hill climb 10/10, random restart 0/10; pure noise 1.4% (14/1,000);
  151/151 worse candidates rejected. Numbers in `specs/phase-3-rsi-framework.md`.

---

## Step 4 — Snakes that improve themselves (phase 4)

### 4.1 Snake evaluator `[x]`
- `arena/evolution/evaluator.py`: fixed-length episodes, paired candidate/champion games
  with identical spawns and opponents, opponent-mixture sampling, seat rotation, guard
  metrics, process pool.
- **Targets:** a candidate identical to the champion yields all-zero paired differences
  (proves pairing is exact); results identical across worker counts.
- *As built:* `SnakeEvaluator` plays each seed's lineup twice in one worker task, so the
  candidate and champion games share spawns, seats and opponents exactly. Evaluation runs
  without the wall-clock move budget (phase 4 spec, As built). Both targets are tests in
  `tests/evolution/test_evaluator.py`.

### 4.2 Lineages and generations `[x]`
- `arena/evolution/lineage.py` and `arena/evolution/run.py`: five lineages, frozen
  champions per generation, fixed order, joint commit, per-lineage patience; `evolve` CLI
  with default and `--quick` profiles.
- **Targets:** `evolve --generations 3 --quick` finishes in < 10 minutes on a laptop and
  in CI; run touches nothing outside `runs/<id>/` (tested by hashing the repo before and
  after).
- *As built:* there is no `lineage.py`. `Lineage` is a small dataclass in `run.py`
  around one phase 3 `Run`, and a generation reads its frozen opponents back from the
  records (phase 4 spec, As built). `evolve --quick --generations 3` took 466 s on the
  4-core cloud container (Measurements). CI runs the tiny evolution tests rather than
  the quick profile, so the CI half of the target is covered by those tests, not by a
  timed quick run. `test_a_run_touches_nothing_outside_its_directory` hashes the
  repository.

### 4.3 Safety tests `[x]`
- Out-of-bounds params, a policy patched to raise, and a proposer that tries to read
  holdout seeds — none can produce a promotion.
- **Targets:** all three tests pass.
- *As built:* `tests/evolution/test_run.py` covers out-of-bounds params, a policy patched
  to raise, and a spy proposer that records every seed it is shown (none come from the
  holdout or final pools). It also checks that a run changes nothing outside its run
  directory.

### 4.4 Reports `[x]`
- `arena/evolution/report.py` + `report` CLI: progress chart with bands, fixed-vs-evolved
  table, all-champions cycle check, 5 × 5 matrix, decision log, behaviour drift.
- **Targets:** report numbers are recomputed from stored records in a test and match.
- *As built:* `report` writes `report.md`, `report.json` and an SVG `progress.svg`
  (no plotting dependency) and refreshes `dashboard.html`, the live per-run dashboard
  that `evolve` also rewrites after every generation. `tests/evolution/test_report.py`
  recomputes the numbers from the records; `test_dashboard.py` checks the page against
  them.

### 4.5 Watch evolved snakes `[x]`
- `watch --run ... --generation N` and `--vs-generation 0`; leaderboard shows versions.
- **Targets:** any archived champion loads and plays after later generations exist.
- *As built:* `arena/evolution/watch.py` turns every archived version into a viewer
  policy (`hunter@v4`, labelled "Hunter v4") and adds lineups: the champions after
  generation N, and with `--vs-generation K` one six-seat lineup per lineage in which its
  generation N and K versions meet the other four generation N champions (a lineup sets
  the seat count). `tests/evolution/test_watch.py` plays every archived version of a
  three-generation run and checks a viewed game against the headless one.

### 4.6 The real experiment `[x]`
- Run `evolve --generations 10` with the default profile (or the labelled experiment
  board from 2.6), generate the report, commit `experiments/<date>-baseline/report.md`
  and charts.
- **Targets:** the report states for each lineage whether it improved on final seeds vs
  generation 0, with intervals. Honest "no improvement" is a valid outcome.
- **Done when:** phase 4 acceptance passes and the README links the report.
- *Status:* done, with two runs, both linked from the README:
  - `experiments/2026-11-12-default/`: the default profile, `evolve --generations 10`.
    It completed with no human input. It stopped after generation 7, once every lineage
    had gone 4 generations without an accept. 1 of 5 lineages improved: Trapper
    (+0.053 kills / 1k ticks on final seeds, 95% CI [+0.024, +0.087], accepted in
    generation 3). The other four are unchanged.
  - `experiments/2026-11-12-baseline/`: the reduced experiment profile. 0 of 5 improved,
    and every lineage ran out of patience after 4 generations.

---

## Step 5 — Stretch (only after step 4)

- `[ ]` 5.1 Meta-run: use the RSI framework to tune `GaussianHillClimb`'s own settings
  (initial σ, growth/shrink factors) on the toy suite — improving the improver, measured.
- `[ ]` 5.2 MAP-Elites over the behaviour grid (aggression × caution).
- `[ ]` 5.3 PBT-style parallel candidates per lineage.
- `[ ]` 5.4 Exploiter snakes trained to beat current champions (AlphaStar-style league).
- `[ ]` 5.5 Optional `LLMProposer` (numbers-only, bounded, budgeted, audit-logged, never
  sees holdout/final seeds); compare against `GaussianHillClimb` under equal episode
  budgets.
- `[ ]` 5.6 Code-level proposer, review-only, until a real sandbox exists (vision §5).
- `[ ]` 5.7 Full React dashboard and SQLite storage from the vision.

---

## Vision coverage

The MVP in [vision.md](vision.md) §2, checked against what is built, as of step 4. Steps
0–4 are what this plan committed to. Everything below marked "not built" is a step 5
stretch item or a deliberate scope change recorded in the phase specs, not a hidden gap.

| Vision item | Status | Where |
|---|---|---|
| 1. Deterministic engine: collisions, respawn, scoring, tests | Built | `arena/engine`, `tests/engine` (golden + invariant tests), step 1 |
| 2. Five strategy agents + seeded random baseline | Built | `arena/agents`, step 2 |
| 3. Fast headless simulation, metrics on disk | Built: `matches.jsonl`, `summary.csv`, `kill_matrix.csv`, replays | `arena/sim`, step 1 |
| 4. Browser arena: live and replay, leaderboard, controls, kill feed | Built with a stdlib server and Canvas page instead of FastAPI and React (phase 1 decision: no web dependencies) | `arena/viz`, `tests/viz/smoke.mjs` |
| 5. Offline evolution driver: propose, test, promote | Built with the local parameter-search improver, so it needs no API | `arena/rsi`, `arena/evolution`, steps 3–4 |
| 5. LLM provider adapter | Not built (step 5.5). Optional in the vision; the default improver covers the demo | — |
| 6. Generation history and version inspection | Built: `report.md`, `progress.svg`, live `dashboard.html`, `watch --run` | `arena/evolution` |
| §7 Experiments screen: start and stop batches from the browser | Not built (step 5.7). Runs start from `evolve`; they stop with `STOP`, `--max-hours` or `--max-episodes` and resume by rerunning | `arena/cli.py` |
| §7 Replay browser with filters, replay bookmarks | Not built (step 5.7). Replays load by file in the viewer | `arena/sim/replay.py` |
| §7 Performance: 100,000 ticks/s (aspirational) | Not reached: about 45,000 ticks/s for the engine alone; measured below | Measurements |
| §8 Seed separation, paired seeds, seat rotation, cost limits, provenance | Built: disjoint dev/holdout/final pools, a spy test, generation/episode/time caps, code and environment hashes in `evolution.json` | `arena/rsi/seeds.py`, `arena/evolution/run.py` |
| §10 Automated acceptance tests: engine, evolution, UI | Built | `tests/engine`, `tests/rsi`, `tests/evolution`, `tests/viz` |
| M5 LLM source improvement, M6 fixed vs parameter-evolving vs LLM comparison | Fixed vs parameter-evolving is done (`experiments/`); the LLM arm is not built (steps 5.5, 5.6) | — |

---

## Measurements

Fill in as steps land. Never estimate here.

| What | Value | Machine | Commit | Step |
|---|---|---|---|---|
| Engine ticks/s (5 × RandomSafe, 100 × 100) | ~45,000 (engine only); ~26,000–30,000 with RandomSafe policies (was ~34,700 and ~18,100 at 94e5abd) | cloud container, Python 3.13, x86_64 | a223d9b | 1.10 |
| RandomSafe kills / 1,000 ticks (100 × 100) | 0.049 all snakes (≈0.01 per snake); 100/100 default matches hit the 100,000-tick cap with ~1 kill per snake | same; 100-match tournament, 10M ticks in 148 s on 4 workers | 2176c31 | 1.10 |
| Personality decision time p50 / p99 (100 × 100) | 0.44–0.81 ms / 0.94–1.95 ms across the five (budget 5 / 20 ms) | cloud container, Python 3.13, x86_64; `bench --policies all --ticks 3000` | 308a67b | 2.6 |
| Personality decision time p50 / p99 after the grid search rewrite | 0.21–0.42 ms / 0.41–0.82 ms; all five together on 100 × 100: ~510–610 ticks/s (was ~260) with identical games (golden digests) | same; `bench --policies all --ticks 3000` | 0847bbb | 4 (speed) |
| Mean ticks to first-to-100 (personalities) | Not reached: 4/4 all-five matches on 100 × 100 hit the 100,000-tick cap with 1 kill in total. On 50 × 50, 4/4 hit the cap with 6 kills in total | same; `run-tournament --matches 4 --policy personalities`, ~410 s per 4 matches on 4 workers | 308a67b | 2.6 |
| Wall time per generation (experiment profile, 24 × 24, 2,000 ticks, 40 + 40 pairs) | 747, 755, 712, 434 s for generations 1-4 (640, 720, 640, 400 episodes); report 12 min | cloud container, 4 cores, 4 workers | 35f7d75 | 4.6 |
| Wall time, `evolve --quick --generations 3` | 466 s in total (145, 162, 159 s per generation) | same, 4 workers (default) | 152c9a0 | 4.2 |
| Paired seeds with any kill, reference context, 40 seeds per lineage | 40 × 40, 1,000 ticks: 0-5; 24 × 24, 2,000 ticks: 1-12 | same, 4 workers | 35f7d75 | 4.6 |
| Wall time per generation (default profile, 100 × 100, 5,000 ticks, 100 + 100 pairs) | 2,885, 3,224, 2,132 s for generations 1-3 (1,600, 1,800, 1,200 episodes; about 7.2 s per episode per worker); report 58 min | cloud container, 4 cores, 4 workers | 3cfed63 | 4.6 |
| Wall time per generation (default profile), generations 4-7 | 2,701 s for generation 4 (1,400 episodes, all five lineages); 338, 393, 373 s for generations 5-7 (Trapper only, 200 episodes each); 12,046 s (3.3 h) for the whole 7-generation run | same | 996ab05 | 4.6 |
| Where an evaluation episode spends its time (profile of one 2,000-tick game, 100 × 100, the five hand-set personalities) | 98% in the policies' move scoring: the territory race 47%, the flood fill 24%, other features the rest. Engine `step` 1.4%. One 2,000-tick game takes 3.0 s, so a 5,000-tick episode takes about 7.5 s; the run measured about 7.7 s per episode per worker, so the RSI loop, evaluator and process pool cost about 3%. Zero-weight features are already skipped. The next speedup has to come from the feature code (or a compiled extension, which the stdlib-only rule excludes), not the framework | cloud container, 4 cores; `cProfile` | ace71d3 | 4 (speed) |
| Lineages improved vs gen 0 (final seeds) | Default profile, 10 generations (stopped at 7 on patience): 1 / 5 (Trapper +0.053 kills / 1k, 95% CI [+0.024, +0.087]; `experiments/2026-11-12-default/`). Experiment profile: 0 / 5 (0 accepts in 4 generations; `experiments/2026-11-12-baseline/`) | same | 3cfed63 / 35f7d75 | 4.6 |
