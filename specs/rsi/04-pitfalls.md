# 4. Pitfalls and Safety Rails

Self-improving systems fail in a few predictable ways. Each pitfall below has a plain
explanation, a snake example, and the rail that stops it in this project.

| # | Pitfall | What it looks like in Snake Arena | Rail | Where |
|---|---|---|---|---|
| 1 | **Luck mistaken for skill** | A candidate wins 3 lucky games and gets promoted | 100 paired games per stage, bootstrap interval must exclude 0, pure-noise test | phase 3 §5, §10 |
| 2 | **Overfitting to the test** | Many small accepted steps all tuned to the same seeds; gains vanish on new seeds | Separate dev / holdout / final seeds; holdout rotation; report on final seeds only | phase 3 §4 |
| 3 | **Reward hacking (Goodhart)** | Kamikaze Hunter: more kills, far more deaths | Guard metrics on deaths and wall/self deaths | phase 4 §3 |
| 4 | **Grading yourself** | Improver edits scoring, evaluator or tests | Improver can only write its own params file; isolation tests after every run | phase 3 §1, phase 4 §1 |
| 5 | **Cycling** | v3 beats v2 beats v1 beats v3 | Hall of fame opponents, reference portfolio, all-champions check in report | phase 3 §7, phase 4 §5 |
| 6 | **Overfitting to one rival** | Survivor learns to dodge only today's Hunter | Mixed opponents incl. historical and random snakes; seat rotation | phase 4 §3 |
| 7 | **Silent rule changes** | Shrinking the board to make kill numbers look better | Rules only change via config with a version and a label in every report | phase 2 §4 |
| 8 | **Irreproducible "progress"** | A result nobody can re-run | Seeded RNG everywhere, stored configs and code hashes, resume tests | phase 3 §3, §9 |
| 9 | **Running untrusted code** | An LLM-written strategy reads files or opens sockets | No code proposals in phases 1–4; LLM proposer returns bounded numbers only; code edits review-only without a real sandbox | phase 3 §6 |
| 10 | **Cherry-picking** | Re-running until a lineage "improves" | Run config fixed up front; report states no-improvement results; decision log keeps every rejection | phase 4 §7 |
| 11 | **Runaway cost** | An evolution run that never ends | Budgets on generations, episodes, time, tokens; patience; STOP file | phase 3 §8 |

## The one rule behind all of them

> **The thing being improved must never control how it is judged.**

The snake controls its strategy. The arena controls the rules. The evaluator controls the
score. The acceptance rule controls promotion. Keep those four separated and most of the
table above follows naturally.
