# 5. Glossary

| Term | Plain meaning |
|---|---|
| **Acceptance rule** | The fixed test a candidate must pass to replace the champion |
| **Archive / hall of fame** | Every accepted version, saved forever and never edited |
| **Bootstrap** | Re-drawing your own results many times to see how much an average could wobble |
| **Candidate** | A proposed new version that hasn't been accepted yet |
| **Champion** | The current best accepted version of a snake |
| **Co-evolution** | Several learners improving at once, so each one's problem keeps changing |
| **Confidence interval** | A range that very likely contains the true value (we use 95%) |
| **Cycling** | A beats B beats C beats A — "improving" forever without getting better overall |
| **Dev seeds** | Practice games used to screen candidates; the proposer may see these results |
| **Episode** | One evaluation game of fixed length |
| **Evaluator** | The code that plays games and produces scores; the improver can't change it |
| **Feature** | A number describing a possible move ("how much space would I have?") |
| **Final seeds** | Games kept untouched until the end, used only for the report |
| **Generation** | One improvement attempt for each of the five snakes |
| **Goodhart's law** | When a number becomes the goal, it stops measuring what you wanted |
| **Group-sequential test** | Checking results at a few planned points and stopping early when clear, with the total error rate fixed in advance |
| **Guard metric** | A secondary number that must not get much worse (e.g. deaths) |
| **Hill climbing** | Small change; keep it if better; repeat |
| **Holdout seeds** | Fresh games the proposer never sees; used for the real accept/reject decision |
| **Lineage** | One snake's chain of versions over time |
| **Local optimum** | A small hilltop: every small step is worse, but a better place exists elsewhere |
| **Paired comparison** | Old and new version play the exact same setups, so luck cancels |
| **Parameter / weight** | A knob in a snake's strategy, e.g. how much it fears walls |
| **Policy** | The function that picks a snake's move each tick |
| **Proposer / improver** | The code that suggests candidates |
| **Racing** | Testing candidates a little at a time and dropping any that is clearly behind |
| **Recursive self-improvement (RSI)** | Improving, then using the improved version to improve again — and improving how you improve |
| **Reference portfolio** | The original hand-made snakes, kept as a fixed yardstick |
| **Reward hacking** | Scoring well by exploiting the scoring rather than by getting good |
| **Seed** | A number that fixes all the randomness of a game, so it can be replayed exactly |
| **Self-play** | Learning by playing against copies of yourself |
| **1/5th success rule** | Grow the step size after successes, shrink it after failures, so ~1 in 5 tries succeeds |
