# AGENTS.md

This file provides shared guidance to Claude Code, Codex, and other coding agents when working with code in this repository.

## What this is

**Snake Arena RSI** — a grid-based, five-snake battle simulator used as a lab for
*recursive self-improvement* (RSI) of agent policies. Five AI snakes fight on a
100 × 100 board for kills; between batches of matches, an improvement loop proposes
changes to each snake's strategy, evaluates them against current and historical
opponents, and keeps only changes that measurably help.

The project studies automated improvement of **agent policies and their parameters**,
not self-modification of any underlying language model.

## Where things stand

The repository is in the **specification stage**. No engine code exists yet. Read the
specs before writing code:

```
README.md                 Short project summary
AGENTS.md / CLAUDE.md     This guidance (CLAUDE.md only points here)
specs/
  README.md               Index of the specs and the order to read them in
  vision.md               The original full product vision (the long-term target)
  phase-1-arena.md        Engine, random snakes, simulation + visualization modes
  phase-2-personalities.md  Five snake personalities / objectives
  phase-3-rsi-framework.md  Generic, snake-agnostic RSI framework
  phase-4-snake-rsi.md    Each snake runs the RSI framework to tune itself
  plan.md                 The step-by-step build plan with concrete targets
  rsi/                    RSI explained simply, algorithms, examples, glossary
```

`specs/plan.md` is the build queue. Work through it in order and tick off steps as they
land. If a step's target turns out wrong, update the spec and the plan in the same
commit as the code change and say why in the commit body.

## Planned architecture

```
arena/
  engine/      Pure, deterministic game rules: state, simultaneous tick resolution,
               collisions, kill credit, respawn, seeded RNG. No I/O, no rendering.
  agents/      Policy interface, the random baseline, the five personalities.
  sim/         Headless match runner, tournaments, metrics, replay files.
  rsi/         The generic RSI framework (knows nothing about snakes).
  evolution/   The glue that plugs snakes into the RSI framework.
  viz/         Visualization mode (terminal and/or browser) that plays live
               matches or saved replays from the same engine.
  cli.py       `python -m arena.cli ...` entry points.
tests/         Mirrors arena/ (tests/engine, tests/agents, ...).
experiments/   Configs, seed lists, champion manifests, reports.
```

## Non-negotiable rules

- **One engine.** Visualization and simulation use the same `arena/engine` code, so a
  rendered game and a headless game with the same seed are identical.
- **Determinism.** Same seed + same policies + same config ⇒ identical events and
  scores. All randomness flows through an explicit, seeded RNG; never call
  `random.random()` or use wall-clock time inside the engine or policies.
- **Engine first.** Rule correctness and kill attribution beat visuals. Every rule in
  `specs/phase-1-arena.md` has a test before the phase is called done.
- **The improver never grades itself.** RSI code may only change a snake's own
  parameters or strategy file. It must never edit the engine, the scoring, the
  evaluator, the tests, the seed lists, or its own acceptance rules.
- **Holdout seeds stay hidden** from whatever proposes changes.
- **No paid APIs required.** The default improver is a local, offline parameter search.
  Any LLM-based improver is optional, opt-in, and review-only unless it runs in a real
  sandbox (see `specs/phase-3-rsi-framework.md`).
- **No unmeasured claims.** Don't write "faster" or "better" in docs or commits without a
  benchmark or evaluation that shows it.

## Development

Python 3.12+. Until the scaffold step in `specs/plan.md` lands, there is nothing to run.
Once it does, the intended commands are:

```bash
uv sync
uv run pytest
uv run python -m arena.cli run-match --seed 42
uv run python -m arena.cli watch --seed 42
uv run python -m arena.cli evolve --generations 3
```

Keep this section in sync with reality as the scaffold lands.

## Testing

- Write the test with the feature. Engine rules get small hand-built board fixtures
  ("golden" tests) plus randomized invariant tests over thousands of ticks.
- Tests never hit the network and never depend on wall-clock timing.
- A phase is done only when its "Done when" checks in `specs/plan.md` pass.

## Conventions

- No code comments unless they explain a non-obvious "why".
- Small modules with pure functions where possible; the engine has no side effects
  beyond the RNG state it is handed.
- Use frozen dataclasses / tuples for anything a policy can see, so policies can't
  mutate shared state.

## Commit and push preferences

- Commit small and often. Each commit should be one focused, self-contained, polished
  change: it builds, its tests pass, and it makes sense on its own. Split unrelated
  changes into separate commits rather than bundling them.
- Push often — after each coherent commit or small group of commits, not at the end of
  a long session.
- Use this commit message format: a relevant one-word label (for example, `docs`,
  `fix`, or `data`), a colon and short description, a blank line, then a longer
  description explaining the change. Choose a label that relates to the short or long
  description; do not use the literal word `title`.

  ```text
  docs: short desc

  long desc...
  ```

- Push changes directly to `main`. Do not open pull requests or work on feature
  branches unless the owner explicitly asks.

- Cloud sessions often start from a shallow clone, and other sessions may push to
  `main` concurrently, so `origin/main` can move past the clone's history. When that
  happens, `main` looks diverged ("ahead N, behind M", "no merge base", or a stop hook
  reporting N unpushed commits) even though nothing local is unpushed. Before you treat
  `main` as diverged, check `git rev-parse --is-shallow-repository`. If it prints
  `true`, run `git fetch --unshallow origin main` and check `git status -sb` again.
  Usually that shows `main` is only behind, and `git pull --ff-only origin main` fixes
  it. Never force-push, reset, or merge unrelated histories to "fix" a divergence you
  haven't confirmed on full history.

- The owner is the author of every commit, and agents are only co-authors. Author and
  commit as `Rayaq Siddiqui <rayaq05@hotmail.com>`, never as the agent's own identity.
  Cloud containers default `user.name`/`user.email` to the agent, so run
  `git config user.name "Rayaq Siddiqui"` and
  `git config user.email rayaq05@hotmail.com` at the start of a session, and check
  `git log -1 --format='%an <%ae>'` before pushing.

- Every commit you create and push must include a `Co-Authored-By` trailer naming the
  model that contributed to it, not just the tool name (Claude Code or Codex). Use the
  actual model name and version available in the session and the provider's
  attribution email. For example:

  ```text
  Co-Authored-By: GPT-6 <noreply@openai.com>
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  ```

  Include only models that contributed to the commit; the lines above are alternatives,
  not a list to copy wholesale. Preserve any existing human or model co-author
  trailers. Check the trailers before pushing.
