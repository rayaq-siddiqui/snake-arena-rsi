# Specs

The contract for what Snake Arena RSI builds. Read in this order:

| File | What it covers |
|---|---|
| [`rsi/`](rsi/README.md) | Background: RSI explained simply, with worked examples and algorithms |
| [`phase-1-arena.md`](phase-1-arena.md) | Engine rules, random snakes, simulation and visualization modes |
| [`phase-2-personalities.md`](phase-2-personalities.md) | Five parameterized personalities |
| [`phase-3-rsi-framework.md`](phase-3-rsi-framework.md) | The generic, snake-agnostic RSI framework |
| [`phase-4-snake-rsi.md`](phase-4-snake-rsi.md) | Each snake runs the framework to tune itself |
| [`plan.md`](plan.md) | The ordered build queue with targets — the file to work from |
| [`vision.md`](vision.md) | The original long-term product vision |

## Key defaults at a glance

| Setting | Value |
|---|---|
| Board | 100 × 100, walls, no wrap |
| Snakes | 5, fixed length 5, respawn after 10 ticks |
| Score | +1 per credited kill (enemy runs into your body) |
| Win | First to 100 kills (tick cap 200,000) |
| Evaluation episode | 5,000 ticks, fixed length, win target off |
| Acceptance | 100 dev + 100 holdout paired games, ≥ +2% gain, 95% bootstrap CI > 0, guard metrics |

Where a phase spec and `vision.md` disagree, the phase spec wins.
