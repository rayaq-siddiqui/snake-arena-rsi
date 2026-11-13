# LLM proposer vs the default hill climber (quick profile)

Plan step 5.5 asked for the `LLMProposer` to be compared against `GaussianHillClimb` at
equal episode budgets. This is a first, small comparison. It is **too small to rank the
two**, and it ran on the rules in force before the board and snake sizes changed.

## Setup

| | Default | LLM |
|---|---|---|
| Command | `evolve --quick --generations 4 --run-id cmp-default` | `evolve --quick --generations 4 --proposer llm --llm-provider openrouter --llm-model deepseek/deepseek-v4.1-flash --max-llm-dollars 2 --run-id cmp-llm` |
| Proposer | Gaussian hill climb | `LLMProposer`: numbers only, sees dev results, never seeds; falls back to the hill climb on a bad reply |
| Profile | quick: 60 × 60 board, 5-cell snakes, 1,000-tick episodes, 20 dev + 20 holdout pairs, kills objective | same |
| Run seed | 0 | 0 |

Both runs stopped after generation 4 on the patience rule (no accept in 4 generations).

## Results

| | Default | LLM |
|---|---|---|
| Accepted changes (5 lineages × 4 generations) | 0 | 0 |
| Candidates that reached the holdout | 6 | 4 |
| Episodes played | 1,120 | 1,080 |
| Wall time | 1,191 s | 1,478 s |
| Model calls | none | 20 (2 failed and fell back to the hill climb) |
| Tokens in / out | none | 26,450 / 47,759 |
| Spend | $0 | $0.035 |

Holdout outcomes (all rejected):

- Default: Predictor −20% (CI reaches 0); Opportunist 0%; Survivor +33%, CI [+0, +0.075]
  reaches 0; Trapper +400%, CI [+0.05, +0.4] but both guard metrics worse; Hunter 0%;
  Trapper +100%, CI reaches 0.
- LLM: Survivor +33% and Predictor +9.1% (twice), CIs reach 0; Trapper 0%.

## Reading

Neither improver found a change that passed the tests in 4 generations. On the quick
profile kills are rare (most paired seeds score 0 kills for both snakes), so most dev
screens tie at a mean difference of 0 and the holdout intervals are wide. With 0 accepts
on both sides, this run cannot tell the two improvers apart. A real comparison needs
more generations and a denser game, such as the `arena` profile (30 × 30, 10-cell
snakes, score objective), which `experiments/` will cover separately.

The LLM run cost $0.035 for 20 calls with `deepseek/deepseek-v4.1-flash` through
OpenRouter. Each call's prompt, reply and cost are in the run's
`lineages/<name>/llm_audit.jsonl` (not copied here; the prompts contain only parameter
names, bounds, champion values and dev results).

Files: `default.log` and `llm.log` are the two runs' console logs.
