# Snake Arena RSI

Five AI snakes fight on a 100 × 100 grid. Each one is trying to make the others crash
into its body, because every kill is a point. Between games, each snake gets to
**improve itself**: it proposes a change to its own strategy, tests that change against
its rivals and against older versions of everyone, and keeps the change only if it
really wins more. Repeat that loop and you have a small, watchable lab for
**recursive self-improvement (RSI)**.

## The game in one paragraph

Five snakes, each a fixed 5 cells long, move one cell per tick at the same time. Hit a
wall, yourself, or another snake and you die. If you die by running into another
snake's body, *that* snake gets a point. Head-on crashes kill both and award nothing.
Dead snakes respawn after a short delay and keep their score. First to 100 kills wins.

## The four phases

1. **Arena** — a correct, deterministic engine with a fast headless simulation mode and
   a visualization mode. The first snakes just move randomly (safely).
2. **Personalities** — each snake gets its own objective: Hunter, Survivor, Trapper,
   Predictor, Opportunist.
3. **RSI framework** — a generic propose → test → keep-or-reject loop that knows nothing
   about snakes, with honest statistics, held-out tests, and a hall of fame.
4. **Snakes that improve themselves** — each snake plugs into the framework and tunes its
   own parameters, generation after generation.

## Read more

- [`specs/`](specs/README.md) — the full specification, one file per phase.
- [`specs/plan.md`](specs/plan.md) — the step-by-step build plan with targets.
- [`specs/rsi/`](specs/rsi/README.md) — RSI explained simply, with examples a high
  schooler can follow.
- [`AGENTS.md`](AGENTS.md) — rules for coding agents working in this repo.

## Status

Specification stage. No code yet; the build starts at step 0 of `specs/plan.md`.
