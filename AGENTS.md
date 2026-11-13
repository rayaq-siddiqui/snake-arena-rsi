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

All four phases are built: the engine, random policies, headless CLIs, replays, the
browser viewer, the five parameterized personalities with their acceptance check, the
generic RSI framework proven on toy problems, and the five self-tuning snake lineages with
their report and viewer support. Read the specs before writing code:

```
README.md                 Short project summary and how to run it
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

## Architecture

The detailed map is the **system-design diagram in [README.md](README.md#system-design)**
(Mermaid, between the `system-design:start` / `end` markers): every module, what it uses,
where run data lands, and the sequence of one evolution generation. Treat it as a living
document that agents maintain and improve:

- Read it before changing how modules connect.
- When you add, move, rename or delete a module, or change what it depends on, update the
  diagram in the same commit. `tests/test_docs.py` fails if a module under `arena/` is
  missing from it.
- When you find it unclear, wrong, or missing something you had to discover by reading
  code (a data flow, an invariant, a file a run writes), improve it, and say what you
  improved in the commit body. Keep it accurate over complete; check that it still renders
  (GitHub renders Mermaid; `<` and `>` must be written as `&lt;` / `&gt;` inside labels).

The short file list:

```
arena/
  engine/      Pure, deterministic game rules (built).
    types.py     Frozen config, state and event types; JSON round-trips.
    rng.py       SplitMix64: the engine's only randomness is one int in GameState.
    spawn.py     Seeded spawn attempts + deterministic fallback scan.
    step.py      new_game(), step(state, actions), rank().
  agents/      Policy interface (base.py), RandomSafe / RandomUniform, name registry.
    features.py  Shared move features over a per-tick Board.
    params.py    Bounded ParamSpace + params/<name>.json (what phase 4 may change).
    scorer.py    Weighted-sum ScoringPolicy; hunter/survivor/trapper/predictor/opportunist.py.
  sim/         Match runner (match.py), tournaments, replays, bench, behaviour metrics,
               personality_check.py (phase 2 acceptance), boards.py (named configs).
  viz/         server.py (stdlib HTTP, pull-based frames) + static/ (Canvas page);
               library.py (replay browser: stored games, filters, bookmarks);
               experiments.py (experiments screen: list, start, stop evolve runs).
  storage/     db.py: SQLite index over run and tournament files (stdlib sqlite3), read-only queries.
  cli.py       `python -m arena.cli run-match | run-tournament | bench | watch | evolve | report`.
  rsi/         The generic RSI framework (NumPy); must not import engine/agents/sim.
    types.py     ParamSpec, Candidate, PairedResult, Decision, Feedback, Budget, protocols.
    seeds.py     Disjoint dev / holdout / final seed pools; rng_for(seed, gen, purpose).
    accept.py    PairedBootstrapRule, opt-in SequentialPairedRule, guard metrics.
    proposers.py Seven built-in proposers (incl. PBT-style `pbt`, `cma_es`) in normalised space.
    llm.py       Optional, opt-in LLMProposer (numbers only, budgeted, audit-logged).
    harness.py   AdaptiveHarness: UCB over the proposers, learned parameter weights, batch.
    coach.py     Opt-in HarnessCoach: a model rewrites a harness's own settings (clipped).
    meta.py      Meta-run: an outer Run tunes GaussianHillClimb's settings on toys.
    map_elites.py  MAP-Elites archive over a behaviour grid; holdout re-score at the end.
    loop.py      Run: propose -> dev screen -> holdout -> accept; budgets, resume.
    store.py     Run directory, atomic writes, immutable archive; report.py, toys.py.
  evolution/   (phase 4) Plugs snakes into the RSI framework.
    entrants.py  Entrant (a policy + its parameters + version) and param_specs().
    evaluator.py SnakeEvaluator: paired games over the opponent mixture; Workers pool.
    run.py       Profiles, Lineage, Evolution (lockstep generations, resume), load_champion.
    report.py    The experiment report: progress vs reference, cycle check, chart.
    watch.py     Archived champions as viewer policies and lineups.
    code_proposer.py  Opt-in, review-only LLM strategy-file patches (never run or applied).
    map_elites.py  One personality's kills over the aggression x caution grid (step 5.2).
    exploit.py   Exploiters trained against frozen champions; the exploit gap (step 5.4).
    cup.py       Arena cup: champions + a random snake play full matches; cup.jsonl.
    league.py    league.json: registered exploiters join later generations' halls of fame.
tests/         Mirrors arena/ (tests/engine, tests/sim, tests/viz, tests/rsi, tests/evolution);
               tests/test_docs.py keeps the README diagram in sync.
docs/          Screenshots.
jj-config.toml Repo jj config (author, `jj fix` tools); scripts/jj-setup.sh installs it.
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

Python 3.12+, managed with `uv`. The engine, simulator and viewer use only the standard
library; dev tools are pytest, hypothesis, ruff and mypy (strict).

```bash
uv sync                                   # install
scripts/jj-setup.sh                       # jj colocated repo + jj fix config (once per checkout)
jj fix                                    # ruff --fix + ruff format on the files you changed
uv run pytest                             # all tests (~5 min on 4 cores; includes engine fuzzing)
uv run ruff check . && uv run ruff format --check . && uv run mypy   # lint, format, types
uv run python -m arena.cli run-match --seed 42                     # one headless match
uv run python -m arena.cli run-tournament --matches 100 --workers 4 --out out/t
uv run python -m arena.cli bench                                  # speed + kill rates
uv run python -m arena.cli bench --workers 4                      # + total ticks/s over 4 processes
uv run python -m arena.cli bench --policies all                   # personality decision times
uv run python -m arena.cli check-personalities --workers 4        # phase 2 acceptance (slow)
uv run python -m arena.cli watch                                  # browser viewer
uv run python -m arena.cli watch --library out                    # + replay browser over out/
uv run python -m arena.cli watch --runs-dir runs                  # + /experiments over runs/
uv run python -m arena.cli rsi-demo --problem quadratic           # RSI loop on a toy
uv run python -m arena.cli rsi-meta --workers 4                   # the loop tunes its own hill climb
uv run python -m arena.cli evolve --quick --proposer llm --max-llm-dollars 2 --run-id llm  # opt-in; needs the llm extra + API key
uv run python -m arena.cli evolve --quick --proposer llm --llm-provider openrouter --llm-model deepseek/deepseek-v4.1-flash --max-llm-dollars 0.4 --run-id llm-or  # opt-in; OPENROUTER_API_KEY
uv run python -m arena.cli propose-code hunter --run runs/demo   # opt-in; review-only patch
uv run python -m arena.cli map-elites hunter --batches 10 --workers 4   # behaviour-grid elites
uv run python -m arena.cli exploit runs/demo hunter --generations 4     # exploiter + league
uv run python -m arena.cli evolve --quick --generations 3 --run-id demo   # snakes tune themselves
uv run python -m arena.cli evolve --generations 10 --max-hours 12 --run-id long  # capped long run
uv run python -m arena.cli evolve --profile arena --generations 1000 --until-wins 100 --run-id cup  # self-tuning harness + cup
uv run python -m arena.cli evolve --profile arena --generations 1000 --until-wins 200 --coach-every 1 --llm-provider openrouter --run-id cup  # opt-in: a model coaches each harness
uv run python -m arena.cli index experiments runs out --db arena.db   # SQLite index (+ --sql)
uv run python -m arena.cli report runs/demo                       # report.md + progress.svg
uv run python -m arena.cli watch --run runs/demo --vs-generation 0   # evolved vs original
```

CI (`.github/workflows/ci.yml`) runs the lint, type and test commands above. The browser
smoke test (`tests/viz/smoke.mjs`, run by `tests/viz/test_browser.py`) needs Node with
Playwright and skips when it isn't installed. Keep this section in sync with reality.

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

- **Use jj (Jujutsu) for version control.** The checkout is a colocated jj + git repo:
  GitHub, CI and read-only `git` commands (`git log`, `git diff`) work as before, but
  make commits, rebases and pushes with `jj`. Run `scripts/jj-setup.sh` once per
  checkout (cloud sessions run it from the environment's setup script). It installs the
  pinned jj release if `jj` is missing, runs `jj git init --colocate`, and copies
  `jj-config.toml` to the repo config path, because jj never reads config from inside
  the working copy. That file sets the commit author and the `jj fix` tools. The
  working copy is itself a commit (`@`), so there is no staging step:

  ```bash
  jj git fetch                                  # update main@origin
  jj new main                                   # start a change on top of main
  # ...edit files...
  jj fix                                        # ruff --fix, then ruff format, on changed files
  uv run ruff check . && uv run mypy && uv run pytest   # jj fix does not type-check or test
  jj describe -m "fix: short desc" -m "long desc..." -m "Co-Authored-By: ..."
  jj bookmark set main -r @                     # move main to this change
  jj git push --bookmark main                   # @ becomes immutable; jj starts a new empty change
  ```

  If `main@origin` moved while you worked, `jj git fetch` and then
  `jj rebase -d main@origin` before `jj bookmark set`. jj refuses to move `main`
  backwards or sideways without `--allow-backwards`; do not pass it, and never force a
  push. When `jj git push` says the remote moved, fetch and rebase instead.

- Cloud sessions may start from a shallow clone. jj handles shallow history, but if
  `main` looks diverged from `main@origin` (or a stop hook reports unpushed commits),
  first check `git rev-parse --is-shallow-repository`. If it prints `true`, run
  `git fetch --unshallow origin main` and `jj git import`, then compare again with
  `jj log -r 'main | main@origin'`. Never force-push, abandon, or rewrite published
  commits to "fix" a divergence you haven't confirmed on full history.

- The owner is the author of every commit, and agents are only co-authors. Author and
  commit as `Rayaq Siddiqui <rayaq05@hotmail.com>`, never as the agent's own identity.
  `jj-config.toml` sets this once `scripts/jj-setup.sh` has run. A change started
  before that keeps the old author, so check `jj log -r @ -T 'author ++ "\n"'` and fix
  it with `jj metaedit --update-author` before pushing.

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
