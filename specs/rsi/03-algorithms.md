# 3. RSI Algorithms, Simply

A tour of the algorithm families behind self-improving systems, from oldest and
simplest to newest. For each: the idea in plain words, an analogy, and whether Snake
Arena uses it.

**Legend:** ✅ built in phases 3–4 · 🔜 planned stretch · 📖 background only

---

## Part 1 — Searching for better numbers ("black-box optimisation")

These treat the thing being improved as a sealed box: put numbers in, get a score out.
They don't need to know *why* a change helps. That's perfect for snake strategies, where
the score comes from playing games.

### Hill climbing / (1+1) evolution strategy ✅

**Idea:** change the current best a little; keep the change if the score goes up.
**Analogy:** climbing a hill in fog, one step at a time.
**Self-improving twist:** Rechenberg's **1/5th success rule** (1973) adapts the step size
from the accept rate (see [Example E](02-worked-examples.md#example-e--the-15th-success-rule-improving-the-improver)).
**Weakness:** gets stuck on small hills.
**In Snake Arena:** `GaussianHillClimb`, the default proposer.

### Random search / random restart ✅

**Idea:** try completely random settings.
**Why it matters:** it's the *control*. If your clever method can't beat random guessing
on the same budget, it isn't clever. Bergstra & Bengio (2012) showed random search is a
surprisingly strong baseline for tuning hyperparameters.
**In Snake Arena:** `RandomRestart`.

### Coordinate search ✅

**Idea:** adjust one knob at a time, up or down; shrink the step when nothing helps.
**Analogy:** tuning a guitar one string at a time.
**In Snake Arena:** `CoordinateSearch`.

### Simulated annealing 📖

**Idea:** like hill climbing, but sometimes *accept a worse step on purpose*, less and
less often as time goes on ("cooling"). That lets it escape small hills early.
**Analogy:** shaking a jar of mixed nuts — hard at first, gently later — so everything
settles into the best arrangement.
**Source:** Kirkpatrick, Gelatt & Vecchi, 1983.
**Why we don't:** deliberately accepting worse champions conflicts with our "only
promote proven improvements" rule. The archive + restarts give us escape routes instead.

### Genetic algorithms 🔜

**Idea:** keep a *population* of solutions. Pick good ones as parents, mix their settings
(crossover), add small random changes (mutation), repeat.
**Analogy:** breeding faster racing pigeons.
**Source:** Holland, 1975.
**In Snake Arena:** `ArchiveCrossover` mixes two archive members — a genetic algorithm
with a population of size "the hall of fame."

### Cross-entropy method and CMA-ES ✅ / 📖

**Idea:** instead of one guess, keep a *cloud* of guesses (a bell curve over settings).
Sample many, keep the best few, move and reshape the cloud toward them.
**Analogy:** a search party that spreads out, then regroups around whoever found clues.
**Sources:** Rubinstein (cross-entropy method, 1999); Hansen & Ostermeier (CMA-ES, 2001),
which also learns which *directions* are promising.
**In Snake Arena:** `CrossEntropy` ✅. CMA-ES is a natural upgrade 📖.

### Evolution strategies at scale 📖

Salimans et al. (OpenAI, 2017) showed simple evolution strategies can train neural
network policies competitively with reinforcement learning, because thousands of
workers can each try a random change in parallel. Lesson for us: our evaluation is
**embarrassingly parallel** — every seed is an independent game — so a process pool
gives near-linear speed-up.

---

## Part 2 — Improving by playing against yourself

### Self-play with a gate ✅

**Idea:** train a new version, make it play the current best, and promote it only if it
wins clearly.
**Real example:** **AlphaGo Zero** (Silver et al., *Nature* 2017) learned Go with no human
games. A new network became the new "best player" only if it won **55%** of **400** games
against the current best. That's an acceptance rule, just like ours (we use 100+100
paired games and a confidence interval instead of a fixed win rate).
**Older example:** TD-Gammon (Tesauro, 1995) reached expert backgammon level through
self-play.

### Population and league training ✅ / 📖

**Idea:** don't just play your latest self — play a whole *league*: past versions,
specialists, and exploiters built to find your weaknesses.
**Real examples:**
- **OpenAI Five** (Dota 2, 2018–19) trained mostly against its current self and partly
  against past versions so it wouldn't forget how to beat old strategies.
- **AlphaStar** (Vinyals et al., *Nature* 2019, StarCraft II) used a league with main
  agents and "exploiter" agents whose job was to find and punish the main agents'
  weaknesses.
**Why:** strategy games have rock-paper-scissors cycles. Only playing your latest self
can go in circles ([Example F](02-worked-examples.md#example-f--rock-paper-scissors-why-we-keep-a-hall-of-fame)).
**In Snake Arena:** opponent mixtures with halls of fame and a fixed reference portfolio
✅; exploiter snakes ✅: `exploit <run> <snake>` trains one against the frozen champions
and, if it finds a weakness, adds it to the run's league so later generations play it. A
Trapper exploiter beat the Trapper champion's kill rate against those champions by +0.11
kills/1k, 95% CI [+0.06, +0.17]
([experiment](../../experiments/2026-11-13-exploiters/README.md)).

### Population Based Training (PBT) ✅

**Idea:** train many copies at once. Every so often, poor performers **copy** the
settings of good performers ("exploit") and then **nudge** them randomly ("explore").
The hyperparameters improve *while* training runs.
**Source:** Jaderberg et al. (DeepMind), 2017.
**In Snake Arena:** the `pbt` proposer runs 4 hill climbers per lineage; each generation
the worst copies one of the best and changes its step size. On toy problems at an equal
game budget it tied the single hill climber
([experiment](../../experiments/2026-11-13-pbt/README.md)).

---

## Part 3 — Keeping many different good ideas ("open-endedness")

### Novelty search 📖

**Idea:** reward being *different*, not just being better. Strange new behaviours become
stepping stones to solutions a greedy search would never reach.
**Analogy:** explorers who map unknown land, even land with no gold, because it leads
somewhere new.
**Source:** Lehman & Stanley, 2011.

### MAP-Elites (quality diversity) 🔜

**Idea:** make a grid of *behaviour types* (e.g. "aggressive & central", "cautious &
near walls") and keep the **best** solution in each cell. You end up with a whole map of
strong, different strategies.
**Source:** Mouret & Clune, 2015.
**In Snake Arena:** a stretch goal using the phase 2 behaviour metrics (aggression ×
caution) as the grid. It would show whether, say, a cautious Hunter can beat an
aggressive one.

---

## Part 4 — Language models that improve code (modern RSI)

These use a large language model (LLM) as the "propose" step: instead of nudging numbers,
the LLM writes or edits code. The model itself never changes; the *programs around it*
improve. All of them still rely on the same propose → test → keep loop.

### The Gödel Machine — the theoretical ancestor 📖

**Idea:** a program that may rewrite *any* part of itself, including how it rewrites
itself, but only after **proving** the rewrite is better.
**Source:** Schmidhuber, 2003.
**Catch:** such proofs are almost never achievable in practice. Every modern system below
swaps "prove it" for "**test it**."

### Reflexion 📖

**Idea:** after failing a task, the LLM writes itself a short note ("I forgot to check the
edge case") and reads it on the next try.
**Source:** Shinn et al., 2023.
**Analogy:** keeping a mistakes journal. For us: the "diagnose" step that summarises why
a snake died is the same idea, and it's what an LLM proposer would read.

### Voyager 📖

**Idea:** an LLM agent in Minecraft that writes code for new skills, tests them in the
game, and saves the ones that work in a growing **skill library** it can reuse.
**Source:** Wang et al., 2023.
**Lesson:** an archive of verified, reusable pieces compounds over time — like our hall of
fame.

### FunSearch 📖

**Idea:** an LLM proposes small programs; an automatic evaluator scores them; the best
are kept in a database and shown back to the LLM as examples for the next round.
**Result:** found new constructions in the *cap set* problem in mathematics.
**Source:** Romera-Paredes et al., *Nature* 2023 (Google DeepMind).
**Lesson:** the **evaluator** is what makes it trustworthy — the LLM can propose
nonsense, and the evaluator throws it out.

### Promptbreeder 📖

**Idea:** evolves the *prompts* given to an LLM — and also evolves the "mutation prompts"
used to change those prompts. Improving the improver, in text.
**Source:** Fernando et al. (Google DeepMind), 2023.

### Eureka 📖

**Idea:** an LLM writes **reward functions** for training robot policies, sees how
training went, and rewrites the reward. Evolutionary search over code.
**Source:** Ma et al. (NVIDIA), 2023.
**Warning for us:** this is exactly why our snakes may **not** edit their own scoring.

### STOP — the Self-Taught Optimizer 📖

**Idea:** start with a simple "improver" program that asks an LLM to improve a given
solution. Then use the improver **on its own code**. The improved improver did better
on downstream tasks, and the LLM proposed strategies like beam search, genetic
algorithms and simulated annealing on its own.
**Source:** Zelikman, Lorch, Mackey & Kalai, 2023 (COLM 2024).
**Honest caveat from the authors:** the underlying language model is unchanged, so it is
"recursively self-improving code generation," not full RSI. They also measured how often
generated code tried to disable its own sandbox — a reason our code-editing proposer is
review-only until a real sandbox exists.

### Darwin Gödel Machine (DGM) 📖

**Idea:** a coding agent that edits **its own source code**, keeps every working version
in a growing **archive**, and picks archive members (not just the latest best) to modify
next — open-ended exploration plus testing on coding benchmarks.
**Result:** reported SWE-bench performance rising from **20.0% to 50.0%**, and Polyglot
from **14.2% to 30.7%**, with ablations showing both self-modification and the archive
mattered.
**Source:** Zhang, Hu, Lu, Lange & Clune, 2025 (Sakana AI / UBC); ICLR 2026.
**Caveats:** very expensive per run, depends on frozen foundation models, and the authors
discuss cases of the agent gaming its own measurements — another argument for an
unbribable judge.

### AlphaEvolve 📖

**Idea:** an evolutionary coding agent: LLMs propose code changes, automated evaluators
score them, a program database keeps the best and most diverse, repeat.
**Results reported by Google DeepMind (2025):** a way to multiply 4×4 complex-valued
matrices with **48** scalar multiplications (improving on Strassen-based 49); a
data-centre scheduling heuristic recovering on average **0.7%** of Google's fleet-wide
compute; a **23%** speed-up of a key kernel, cutting Gemini's training time by about 1%.
**Lesson:** "LLM proposes + machine checks + archive" is the pattern that works at the
frontier. It's the code-level version of what we do with numbers.

### Where research stood in 2026 📖

Surveys from 2026 (for example Chen, Wang & Qu, *"Recursive Self-Improvement in AI: From
Bounded Self-Refinement to Autonomous Research Loops"*, arXiv:2607.07663) separate
**bounded self-refinement** — improving within a fixed evaluator, like Snake Arena — from
**open-ended RSI**, and note open-ended loops are limited by grounding (needing a real
external check), collapse dynamics and compute. Several 2026 preprints stress that the
external evaluation target must stay fixed for improvement claims to mean anything.

---

## Part 5 — The statistics that keep it honest

| Tool | Plain meaning | Used for |
|---|---|---|
| **Paired comparison** | Compare old vs new on the *same* games so luck cancels | Every evaluation ✅ |
| **Bootstrap** (Efron, 1979) | Re-draw your own data many times to see how much the average could wobble | Confidence interval in the acceptance rule ✅ |
| **Holdout set** | Fresh test cases the improver never saw | Accept/reject decision ✅ |
| **Multiple-comparisons awareness** | Try enough ideas and some look great by luck | Why dev ≠ holdout, and the pure-noise test ✅ |
| **Goodhart's law** | "When a measure becomes a target, it ceases to be a good measure" | Guard metrics against kamikaze snakes ✅ |

---

## How Snake Arena maps onto all this

| Piece of the loop | Snake Arena choice | Inspired by |
|---|---|---|
| What improves | Each snake's parameter vector (level 1) | Black-box optimisation |
| Proposer | Hill climbing with 1/5th rule, coordinate search, cross-entropy, archive crossover; random restart as control | ES, CEM, GA |
| Improving the improver | Step size and parameter choice adapt from accept history | 1/5th rule, Promptbreeder (in spirit) |
| Opponents | Current rivals + halls of fame + fixed reference portfolio | AlphaStar league, OpenAI Five |
| Gate | Paired dev screen → holdout bootstrap → guard metrics | AlphaGo Zero's evaluator |
| Archive | Immutable hall of fame per lineage | DGM, FunSearch, Voyager |
| Code edits | Not in phases 1–4; future LLM proposer is numbers-only, code is review-only without a sandbox | STOP's sandbox findings |

## Sources

- I. J. Good, "Speculations Concerning the First Ultraintelligent Machine," 1965.
- I. Rechenberg, *Evolutionsstrategie*, 1973.
- J. Holland, *Adaptation in Natural and Artificial Systems*, 1975.
- B. Efron, "Bootstrap Methods: Another Look at the Jackknife," *Annals of Statistics*, 1979.
- S. Kirkpatrick, C. Gelatt, M. Vecchi, "Optimization by Simulated Annealing," *Science*, 1983.
- G. Tesauro, "Temporal Difference Learning and TD-Gammon," *CACM*, 1995.
- R. Rubinstein, "The Cross-Entropy Method for Combinatorial and Continuous Optimization," 1999.
- N. Hansen, A. Ostermeier, "Completely Derandomized Self-Adaptation in Evolution Strategies," 2001.
- J. Schmidhuber, "Gödel Machines: Self-Referential Universal Problem Solvers Making Provably Optimal Self-Improvements," arXiv:cs/0309048, 2003.
- J. Lehman, K. Stanley, "Abandoning Objectives: Evolution Through the Search for Novelty Alone," 2011.
- J. Bergstra, Y. Bengio, "Random Search for Hyper-Parameter Optimization," *JMLR*, 2012.
- J.-B. Mouret, J. Clune, "Illuminating search spaces by mapping elites," arXiv:1504.04909, 2015.
- T. Salimans et al., "Evolution Strategies as a Scalable Alternative to Reinforcement Learning," arXiv:1703.03864, 2017.
- M. Jaderberg et al., "Population Based Training of Neural Networks," arXiv:1711.09846, 2017.
- D. Silver et al., "Mastering the game of Go without human knowledge," *Nature*, 2017.
- O. Vinyals et al., "Grandmaster level in StarCraft II using multi-agent reinforcement learning," *Nature*, 2019.
- OpenAI et al., "Dota 2 with Large Scale Deep Reinforcement Learning," arXiv:1912.06680, 2019.
- N. Shinn et al., "Reflexion: Language Agents with Verbal Reinforcement Learning," arXiv:2303.11366, 2023.
- G. Wang et al., "Voyager: An Open-Ended Embodied Agent with Large Language Models," arXiv:2305.16291, 2023.
- C. Fernando et al., "Promptbreeder: Self-Referential Self-Improvement via Prompt Evolution," arXiv:2309.16797, 2023.
- E. Zelikman, E. Lorch, L. Mackey, A. T. Kalai, "Self-Taught Optimizer (STOP): Recursively Self-Improving Code Generation," arXiv:2310.02304, 2023.
- Y. J. Ma et al., "Eureka: Human-Level Reward Design via Coding Large Language Models," arXiv:2310.12931, 2023.
- B. Romera-Paredes et al., "Mathematical discoveries from program search with large language models," *Nature*, 2023.
- Google DeepMind, "AlphaEvolve: A Gemini-powered coding agent for designing advanced algorithms," 2025.
- J. Zhang, S. Hu, C. Lu, R. Lange, J. Clune, "Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents," arXiv:2505.22954, 2025 — and [sakana.ai/dgm](https://sakana.ai/dgm/).
- Chen, Wang & Qu, "Recursive Self-Improvement in AI: From Bounded Self-Refinement to Autonomous Research Loops," arXiv:2607.07663, 2026.
