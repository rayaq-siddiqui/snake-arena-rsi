> **How this file relates to the phase specs.** This is the original long-term product
> vision, kept as written. The phase specs (`phase-1-arena.md` … `phase-4-snake-rsi.md`)
> are the contract for what gets built now. Where they disagree, the phase specs win.
> The main deliberate differences: snakes are **5** cells long (not 8), and a match ends
> when a snake reaches **100 kills** (with a tick cap as a safety net) instead of after a
> fixed 5,000 ticks. Phase 1 ships a lightweight Canvas viewer instead of the full
> React/FastAPI dashboard, and SQLite storage and the LLM improver are later work, not
> part of phases 1–4.

# Snake Arena — Multi-Agent Recursive Improvement Lab

**Status:** Build-ready specification (v0.1)  
**Working name:** Snake Arena  
**Primary objective:** Build a reproducible, visually engaging sandbox where **five independently evolving Snake agents** compete for kills in a persistent arena, then improve their decision-making code across generations.

## 1. Product vision

Build a top-down, grid-based multiplayer Snake battle simulator. Five AI-controlled snakes fight on a large board. Each snake has a **fixed length** and respawns after death. The only primary score is **credited kills**. Matches last a fixed number of ticks; evolution occurs **between** batches of matches, not mid-match. An LLM-powered code improvement loop proposes changes to each agent's strategy, evaluates them against opponents and historical champions, and accepts only valid improvements.

The project is a study of **automated improvement of agent policies/source code**, not self-modification of the underlying LLM. A successful release makes the progress measurable and the matches watchable.

### User stories
- As a viewer, I can watch five colored snakes compete and inspect live kill/death scores.
- As an experimenter, I can run thousands of deterministic matches without rendering.
- As a researcher, I can compare agents across generations using reproducible seeds and a historical-agent pool.
- As a developer, I can replace an agent's policy without modifying the game engine.
- As an operator, I can trigger/pause an evolution batch, review proposed code changes, and roll back failures.

## 2. MVP scope and non-goals

### MVP (build in order)
1. Pure deterministic game engine with collision/respawn/scoring and tests.
2. Five initial agents with different strategy heuristics, plus seeded random baseline.
3. Fast headless simulation and match metrics persisted to disk.
4. Browser dashboard with live/replayable arena, leaderboard and controls.
5. Offline evolution driver that proposes, tests, and promotes strategy modifications; support an **LLM provider adapter**, but default to a local no-API-cost parameter-mutation improver so the demo works without credentials.
6. Generation/history visualization and agent-version inspection.

### Explicit non-goals for MVP
- Real networked human multiplayer, accounts, user-generated untrusted plug-ins, production-scale hosted tournaments, RL training infrastructure, distributed GPU training, and live self-editing while a match is running.
- Never let generated strategies edit engine rules, evaluator, scoring, seed selection, tests, or their own acceptance criteria.

## 3. Game rules (authoritative defaults, all configurable)

| Setting | Default |
|---|---|
| Board | 100 × 100 cells, bounded, no wrap |
| Competitors | Exactly 5 persistent agent identities |
| Snake size | Fixed **8 cells** (no growth); configurable 5–10 |
| Directions | Up/down/left/right, grid-aligned; no immediate 180° reversal |
| Update rate (viewer) | 10 ticks/second; headless uncapped |
| Movement | **Simultaneous** one-cell step per alive snake per tick |
| Spawn | Random seeded valid empty straight run of 8 cells with safe clearance |
| Death | Out-of-bounds, collision with occupied body, head-on collision, or head-swap |
| Respawn | After 10 ticks, on a safe location; retry each tick if no space |
| Match duration | 5,000 ticks |
| Primary score | +1 per credited enemy elimination; deaths have no direct point penalty |
| Secondary analytics | Deaths, kill/death ratio, kills per 1,000 alive ticks, survival, opponent pairwise encounters |
| Controls | Pause, resume, reset, change speed, seed, inspect snake |

### Precise collision semantics
1. At tick start, collect **one action per living agent** from the same immutable snapshot. If an agent errors/times out, fall back to a safe legal action chosen deterministically; log the violation.
2. Convert each action to next head cell; disallow reverse moves (invalid reverse means continue straight). No agent gets to observe another's action before deciding.
3. All snakes vacate their tail cell when advancing, since length is fixed. A move into a tail cell **vacated on this tick** is allowed unless another collision applies.
4. All other cells occupied by bodies **after tail removal** are hazardous. Entering any body's occupied cell kills the moving snake.
5. If two or more heads target the same cell, **all colliding heads die**. If two heads swap positions, both die.
6. Collision with a wall or one's own body causes death but earns no kill for another agent.
7. If A's head strikes B's body and B remains the owner of that body segment in the collision snapshot, B gets **+1 kill**, even if B also dies in the same tick. A dead snake can be credited for a kill on that simultaneous tick.
8. If multiple deaths are attributable to one snake's body in a tick, that owner earns one point **per distinct victim**. Head-on and head-swap collisions award **no kill** (to avoid arbitrary attribution). The event log records victim, credited killer or null, and collision type.
9. All collisions and kill credits are resolved from the **same pre-commit state** and intended next positions; do not depend on iteration order. Remove dead snakes together, then commit survivors and decrement respawn counters. Spawn only after movement/collision resolution.
10. Respawning snakes have a new life ID but keep their agent ID, cumulative score, policy version and strategy. New spawns must not overlap alive snakes; use seeded spawn attempts and deterministic fallback search.

**Important edge case:** A body belonging to a snake that dies this tick still counts as a collision hazard and may earn a simultaneous kill, based on the post-tail-removal collision snapshot.

### Scoring and ranking
- Primary match winner = most **credited kills** after 5,000 ticks. Ties: fewer deaths; then greater alive-tick survival; then shared rank if still tied.
- No survival points in the official score. Survival statistics are diagnostic and can be part of *offline* selection, but never silently change match scoring.
- Consider collisions per opponent and exposure-adjusted kill rate to avoid selecting blindly aggressive suicide bots.

## 4. AI observation and action API

Agents receive **read-only information** about the current board and public positions, plus their own ID. For MVP, agents have full visibility of the arena (no fog of war). They never receive other agents' planned actions or internal source code.

Python contract (illustrative):

```python
from dataclasses import dataclass
from typing import Literal, Protocol

Direction = Literal["UP", "DOWN", "LEFT", "RIGHT"]

@dataclass(frozen=True)
class Observation:
    tick: int
    board_width: int
    board_height: int
    self_id: str
    snakes: tuple  # immutable public snake views: id, body cells, heading, alive

class Policy(Protocol):
    def choose_action(self, observation: Observation) -> Direction: ...
```

Use concrete immutable typed structures in implementation; the above is not the complete type schema. Agent decision budgets: **20 ms wall-clock per move in viewer mode** (configurable). For experiments, enforce per-agent CPU or process limits rather than relying only on an in-process timer.

### Five starting policy identities
1. **Hunter** — closes distance to vulnerable enemy heads, with collision avoidance.
2. **Survivor** — maximizes safety/available space, minimizing death exposure.
3. **Trapper** — seeks intersections and body positioning that constrain opponents' safe options.
4. **Predictor** — scores moves by possible opponent next-head positions and collision risk.
5. **Opportunist** — balances safety with high-probability eliminations.

These are starting priors, not permanent behavioral constraints. Each agent must be free to improve and change tactics independently. Give each identity an independent policy file/config, version line, score history, and improvement log.

## 5. Improvement and selection system

### Terminology
- **Match:** 5,000-tick game among five agent versions, with seeded spawns.
- **Evaluation batch:** Many matches with balanced seed and seat/identity permutations.
- **Generation:** One proposed candidate and accept/reject decision per agent (can be sequential for reproducibility).
- **Champion:** Best accepted version of a named agent according to the evaluator.
- **Hall of fame:** Immutable saved versions from previous generations, used as opponents.

### Iteration pipeline
1. **Freeze** the five current champions and snapshot the generation configuration, seeds, and code hashes.
2. **Diagnose** each agent using match results, kill/death breakdown, failure examples, and selected replay traces.
3. **Propose** one isolated patch to the agent's editable strategy file(s), either via a built-in deterministic parameter search or an optional coding LLM.
4. **Validate** patch syntax, interface contracts, static restrictions, test suite, resource limits, and runtime stability.
5. **Benchmark** candidate versus current champion on identical precommitted **development seeds** and multiple opponent mixtures, including recent and historical opponents. Rotate starting identity/spawn ordering to reduce positional bias.
6. **Confirm** a promising candidate on a second **holdout** seed set that was not shared with the proposer; keep a final benchmark set untouched for reporting.
7. **Promote** only if acceptance criteria are met. Otherwise retain champion and record rejection rationale.
8. **Archive** patch diff, source hash, test results, metrics, and decision; proceed to the next generation.

### Initial acceptance policy
- Candidate must pass **100%** of engine/API/security tests and have **zero** crashes/timeouts on validation games.
- Run at least **100 paired development matches** and **100 paired holdout matches** for each candidate initially; scale up if differences are noisy. Use common random seeds where feasible.
- Primary comparator: average credited kills per 1,000 **match ticks**, with wins and deaths as secondary diagnostics. Evaluate both versus a fixed reference opponent portfolio and in mixed contemporary/historical tournaments.
- Promote only if holdout mean primary metric improves by a configurable margin (start at **+2%**) **and** bootstrap confidence interval for paired difference excludes zero. Do not infer significance from a single lucky match.
- Reject significant regressions in match win rate or catastrophic death spikes; publish all metric trade-offs.
- Stop on generation cap, API cost budget, no-improvement patience, or manual pause. Keep detailed logs, even when no candidate is accepted.

### Why hall of fame matters
Co-evolution may be cyclical: A beats B, B beats C, and C beats A. Keep an archive of the first baseline and milestone champions, and sample archive opponents at evaluation time so the system cannot overfit to one current rival. Report a **5×5 head-to-head kill matrix** and historical benchmark performance per generation.

### Two improver adapters
**Baseline (no external keys):** mutate numerical coefficients/heuristics or choose among predefined policy modules. Fully offline, reproducible, suitable for end-to-end tests.

**Optional LLM code improver:** provider-agnostic interface takes one policy's current source, summary of failure modes, allowed edit scope, improvement budget and requested diff; outputs a candidate **patch only**. Keep prompt/response logs, model identifier and API spend. It does not write into the running server or trigger unsafe operations.

### Security boundary (critical)
- Treat generated code as **untrusted**. Never execute LLM-authored Python directly in the main application process or on a developer's unrestricted machine.
- In the first implementation, run code-improvement support only behind an explicit opt-in and a hardened **isolated sandbox** (container/microVM or equivalent) with **no network access, no host filesystem access, a read-only engine, restricted mounts, non-root identity, capped memory/CPU/time, and no credentials**. AST-based checks alone are not a sandbox.
- If a secure execution boundary cannot be provided, ship the baseline optimizer and make LLM code proposals **review-only**, with manual promotion. Never claim arbitrary generated Python is safe.
- Only the evaluator can calculate rewards and promote versions. Code changes cannot modify engine/tests/scoring/evaluator or read holdout seeds.

## 6. Proposed architecture and stack

**Recommended stack:** Python 3.12+, `pytest`, `pydantic` or dataclasses for typed models, FastAPI + WebSockets for an optional backend service, React + TypeScript + Vite + HTML Canvas for visual UI, SQLite for experiment metadata and JSONL for detailed events. Use a simple `uv` or pip-based development workflow. Avoid unnecessary distributed components.

```text
snake-arena/
  README.md
  SPEC.md
  pyproject.toml
  arena/
    engine/        # state, simultaneous tick resolution, RNG, collision, respawn
    agents/        # Policy interface, five seed policies, random baseline
    eval/          # seeded tournament runner, paired comparisons, metrics
    evolution/     # experiment scheduler, patch proposal, promotion, archives
    storage/       # SQLite models, JSONL results, replay serialization
    api/           # FastAPI routes + WebSocket live game stream
  frontend/
    src/           # Canvas arena, scoreboards, charts, replays, experiment UI
  tests/
    engine/        # property tests and edge cases
    agents/
    eval/
    evolution/
  experiments/     # configs, seeds, reports, champion manifest
  docs/
```

Keep a **single engine package** used by UI and evaluation so rendered games and headless games cannot disagree. Avoid coupling rendering frame rate to simulation ticks. Use seedable RNG stored with every run.

### Interfaces and storage
- `step(state, actions) -> next_state, events` is pure except explicit RNG state; deterministic given state + actions.
- `simulate_match(policies, seed, config) -> MatchResult` streams optional events to a replay log.
- `evaluate(candidate, reference, opponents, seeds) -> ComparisonReport` includes sample size, paired metrics and uncertainty.
- `propose_patch(agent, diagnostics, constraints) -> CandidatePatch` is replaceable per improver.
- SQLite tables/records: `agents`, `policy_versions`, `matches`, `match_participants`, `kill_events`, `generations`, `candidate_evaluations`, `promotion_decisions`.
- Replay JSON includes config version, RNG seed, initial states, per-tick actions/events and source version hashes. Version replay schema for forward compatibility.

## 7. Dashboard UX

### Main screen: Arena
- Large dark-background grid with five clearly contrasting snake colors, distinct head markers and smooth interpolation between discrete ticks.
- Live leaderboard: agent name, version, kills, deaths, K/D, current life duration, respawn countdown.
- Controls: play/pause, speed (1× / 2× / 5× / 10×), seed, new match, show/hide trails, select/follow agent.
- Highlight eliminations (brief effect + kill-feed: `Hunter eliminated Survivor`). Head-on ties show `collision: no killer` rather than assigning arbitrary scores.

### Experiments screen
- Start/stop an offline batch; configure tick count, number of matches, generation count, cost budget, seed pool, improver adapter.
- Line chart: per-agent benchmark kill rates over generations, with uncertainty bands.
- Matrix: head-to-head elimination counts/rates across the five agents.
- Version timeline: accepted/rejected candidate patches, code diff, metrics, changelog and rollback.
- Replay browser filters by generation, winner, matchup, collision and interesting moments.

### Performance targets
- Headless engine handles **at least 100,000 ticks/second** on a typical development laptop with simple heuristic agents (aspirational target; benchmark and document actual result).
- Viewer remains responsive at 10 ticks/second and can replay stored matches without rerunning agents.
- UI runs locally without cloud services, credentials or LLM access.

## 8. Reproducibility and fairness

- Record Python and dependency versions, configuration hash, seed list, policy source hashes and evaluation code revision for each experiment.
- Separate **development**, **holdout selection** and **final reporting** seeds. Never expose holdout/final seeds to an LLM proposer.
- Agents do not see RNG state, other agents' future actions or opponent policy source.
- Use identical environment seeds and balanced ordering/rotation when comparing candidates; avoid selecting candidates based only on games against themselves.
- Control experiment cost: hard limits for matches, generations, elapsed runtime, token spend and patch attempts.
- Replays and score calculations must match engine events exactly.

## 9. Build plan / milestones

### M0 — Scaffold
- Python project with formatter/linter/type checker/test commands, minimal README, deterministic configuration, CI.
- **Done when:** clean checkout installs/runs tests with documented commands.

### M1 — Correct game engine
- Grid model, simultaneous movement, fixed length, wall/self/body/head-on/head-swap/vacated-tail cases, kill attribution, timed respawn, reproducible seeds.
- **Done when:** deterministic golden tests pass; invariants hold across thousands of random ticks.

### M2 — Baseline AI tournament
- Five named policies and random baseline; headless matches; events and metrics; export CSV/JSON; CLI `run-match`, `run-tournament`.
- **Done when:** 100 deterministic matches produce reproducible scores and per-opponent stats.

### M3 — Viewable application
- FastAPI streaming/replay endpoint and browser Canvas UI, scoreboard, controls, saved replays.
- **Done when:** launching locally displays a five-snake match, kills/deaths and respawn in real time.

### M4 — Offline evolving population
- Parameter mutation baseline, candidate evaluation, held-out testing, archival, hall of fame, automatic promotion/rejection, charts.
- **Done when:** 3 full generations complete without human edits; versions/decisions are reproducible and inspectable.

### M5 — Optional LLM-driven source improvement
- Provider interface; strategy-scoped diffs; secure isolated runner or review-only mode; cost caps and audit logs.
- **Done when:** generated candidate is proposed, validated, compared against champion, and promoted/rejected with evidence; unsafe code never runs unsandboxed.

### M6 — Polish and research report
- Replay bookmarks, performance profiling, documentation, experiment examples, end-to-end tests, comparison of fixed vs parameter-evolving vs LLM-code-improving policies.
- **Done when:** repo can demonstrate an honest, repeatable improvement experiment with baseline comparisons.

## 10. Acceptance tests (must automate)

### Engine
- Same seed + same policies + same config = identical match events and final standings.
- Every alive snake has exactly 8 contiguous unique cells; heads move max one cell per tick and cannot reverse.
- Snake dies on wall, own body and other body, including simultaneous multi-kill situations.
- Entering a cell vacated by a tail this tick is allowed, absent another collision.
- Two heads into one cell both die; crossed heads both die; neither produces a kill credit.
- Hitting an opponent's body credits exactly one kill to owner, including if owner dies simultaneously.
- No spawn overlaps any occupied cell; failed spawns retry rather than crash.
- Score persists through respawns; no growth occurs.

### Evaluation and evolution
- Candidate cannot alter engine, metrics, tests or immutable hall-of-fame versions.
- Failed/invalid patches never become champions.
- Same candidate and fixed evaluation fixtures yields identical metrics/decision.
- Runs honor match/generation/runtime/cost limits and can resume from the last committed generation.
- Holdout seeds do not appear in proposer inputs or publicly displayed diagnostics while selection is active.
- Historical champion remains retrievable and replayable after later evolution.

### UI
- Leaderboard values match server events and replay results.
- Pause prevents tick progression; speed controls affect only playback, not game results.
- Dead snakes disappear, respawn timer appears, and respawned identity retains cumulative score.

## 11. Key design risks / decisions

1. **Kill attribution vs head collisions:** Rules above deliberately award no points for symmetric head-on crashes. Consider alternative rules only through an explicit rules version.
2. **Large board and only five snakes:** A 100×100 arena may make encounters rare. Add configurable arena density and measure actual kills per 1,000 ticks. If necessary tune to 60×60 or use encounter incentives rather than silently changing mechanics.
3. **Short fixed bodies:** Smart interception may be challenging without temporary hazards; start with simple rules, evaluate, then consider optional modes.
4. **Five distinct AIs vs five distinct improvers:** MVP uses **five independent policy lineages** under the *same* improvement protocol, for a fair comparison. Later experiment: compare LLM editing, evolutionary search and RL under equal budget.
5. **Optimization overfitting:** Use multiple seeds, historic opponents and holdouts; track unexpected tactics and degenerate behavior.
6. **Resource/security boundaries:** Untrusted generated code requires true isolation. Default-safe offline optimizer must remain fully usable.

## 12. Stretch ideas (after MVP)

- ELO-like ratings through controlled head-to-head tournaments (in addition to kill-based scoring).
- Fog-of-war, obstacles and shrinking safe zone as separate rules variants.
- Spectator camera, heat maps, danger maps, kill replays, tactics classifier.
- Human-controlled snake against evolved champions.
- Team/cooperative modes; multiple arenas; tournament brackets.
- Experiment with **five different improvement algorithms** while enforcing equal compute/API budgets.
- Offline training from collected match trajectories and optional RL policies.

---

## 13. Instructions for the coding agent

**You are the implementation agent for this repository.** Implement the above specification incrementally. Prioritize a correct, deterministic engine and a usable headless benchmark before UI polish or any LLM integration.

1. Inspect repository state. If empty, scaffold Python + React/TypeScript projects using the proposed stack.
2. Write a short implementation plan in `docs/IMPLEMENTATION_PLAN.md` with M0–M5 tasks and assumptions. Do not block on decisions with defaults specified above.
3. Implement M0, M1, M2, and M3 first. Include tests and a functioning local run path. Then implement M4 with a safe no-key baseline improver. Treat M5 as optional until secure isolation or review-only mode exists.
4. Build small, testable modules. Engine rules and event attribution take precedence over visuals. Never let code from the improver modify engine or evaluation files.
5. Create `README.md` with setup, precise CLI commands, commands to start the viewer, sample outputs, test commands, architecture diagram and current limitations.
6. After every milestone, run tests and report what passed, what remains, and any deviations from spec. Do not claim performance or improvement without measured benchmarks.
7. Deliver a working demo with five different policy strategies, real-time scoreboard, death/respawn, seed-controlled replays, 100-match headless tournament, and a reproducible 3-generation offline parameter-evolution experiment.

### Suggested demo commands (implement equivalents)

```bash
uv sync
uv run pytest
uv run python -m arena.cli run-match --seed 42 --ticks 5000
uv run python -m arena.cli run-tournament --matches 100 --ticks 5000
uv run python -m arena.cli evolve --generations 3 --improver parameters
uv run uvicorn arena.api.app:app --reload
# in another terminal:
cd frontend && npm install && npm run dev
```

**Definition of complete MVP:** All M0–M4 acceptance criteria above hold; a fresh clone with no paid API keys can run reproducible headless experiments and watch live matches; the README explains how to do both. M5 is a gated extension, not a dependency of the MVP.
