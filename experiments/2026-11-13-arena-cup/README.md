# 2026-11-13 Arena cup to 200 wins with self-tuning, coached harnesses (plan step 5.8)

**Result: the Hunter reached 200 cup wins (204) in generation 26.** Final standings:
Hunter 204, Trapper 135, Opportunist 134, Predictor 117, Survivor 34, random snake 0.
Three lineages accepted a change (Survivor and Opportunist in generation 3, Trapper in
generation 11). On the untouched final seeds, Survivor's and Opportunist's gains held and
Trapper's did not reach significance. **The Hunter won on its hand-set parameters**: its
harness found candidates that won on holdout twice, but the death guard rejected both. Halfway
through, the run got faster: from generation 11, each generation took about 740 s instead of
about 1,320 s (see [Speed](#speed)).

- **Setup:** `evolve --profile arena --generations 1000 --until-wins 200 --coach-every 1
  --llm-provider openrouter --run-id arena-cup`, 4 workers. Each lineage is one of the five
  personalities, tuned by an `AdaptiveHarness` (`arena/rsi/harness.py`). The harness runs a
  UCB bandit over six search operators, learns per-parameter weights, and sizes its own
  batch. The `arena` profile trains on a 30 × 30 board with 2,000-tick episodes and the
  `score` objective (kills minus self-inflicted deaths). Acceptance uses paired bootstrap
  on holdout seeds plus guard metrics. After each generation, the five champions and a
  `random_safe` snake play 24 cup matches with the real win rule (first to 10 points),
  and wins add up in `cup.jsonl`.
- **The harness evolving itself:** from generation 9, a `HarnessCoach`
  (`arena/rsi/coach.py`) called `deepseek/deepseek-v4.1-flash` via OpenRouter once per
  lineage per generation. Each call read the harness's learned state and the snake's
  strategy brief, then patched the harness's own settings:
  - operator biases;
  - parameter priors;
  - the exploration constant;
  - the largest batch.

  Every patch is numbers only, clipped, and audit-logged. The coach sees dev feedback only.
- **Files:**
  - `cup.jsonl`: every cup match;
  - `timing.jsonl`: seconds and episodes per generation;
  - `champions.json`: the final champion parameters per lineage;
  - `coach_patches.jsonl`: every coach call, with its patch, rationale and cost. The prompts
    and raw replies stay in the run directory.

## Cup standings

| Snake | Wins by gen 10 | Wins in gens 11–26 | Total |
|---|---|---|---|
| Hunter | 87 | 117 | **204** |
| Trapper | 40 | 95 | 135 |
| Opportunist | 48 | 86 | 134 |
| Predictor | 49 | 68 | 117 |
| Survivor | 16 | 18 | 34 |
| `random_safe` | 0 | 0 | 0 |

The Hunter passed 100 wins in generation 12 and 200 in generation 26. The Trapper's share
rose after its generation-11 accept: it won 40 of 240 matches before and 95 of 384 after.

## Accepts and final-seed checks

| Lineage | Accepted | Change vs hand-set | Final seeds: score / 1k ticks, cand − champ [95% CI] |
|---|---|---|---|
| Hunter | none (2 guard rejects: gen 5 +47.5%, gen 8 +27.9%, on deaths per 1k alive) | — | — |
| Survivor | gen 3, holdout +316.7% | `keep_distance` 3 → 1, `keep_repel` 1 → 0 | +0.417 [+0.167, +0.675] |
| Trapper | gen 11, holdout +411.1% | `keep_distance` 3 → 0 | +0.092 [−0.117, +0.292], not significant |
| Predictor | none | — | — |
| Opportunist | gen 3, holdout +208.3% | `keep_distance` 4 → 2 | +0.392 [+0.150, +0.658] |

The three accepted changes all moved one parameter in the same direction: they let the snake
come closer to its rivals. On the final seeds, the Survivor's deaths per 1k alive ticks rose
from 0.217 to 0.284. The Trapper's self/wall deaths rose from 0.017 to 0.233, even though its
deaths per 1k alive fell from 0.377 to 0.234. So the Trapper's change is a trade, not a clean
gain.

## How each harness evolved, and the final strategy

Every harness learned the same thing about operators. `gaussian_hill_climb` earned 0.35–0.44
mean reward per use in every lineage, and every other operator earned 0–0.18. The broad
operators (`cma_es`, `cross_entropy`, `archive_crossover`, `random_restart`) mostly proposed
large multi-parameter jumps that lost dev games badly. From its first patches, the coach
read this from the harness state. By the end it had:
- set `gaussian_hill_climb` to the maximum bias (+1.0);
- pushed the broad operators to −0.7…−1.0;
- left `coordinate_search` near neutral, because it produced the Trapper's only accept.

The coach also raised the batch ceiling to 6 for every lineage, because generations kept
ending with no accept. Where the lineages differ is the parameter priors: which strategy
terms the harness's steps concentrate on.

| Lineage | Operator uses, discounted (gaussian / all) | Final explore | Highest priors (coach) | Lowest priors |
|---|---|---|---|---|
| Hunter | 34 / 56 | 1.95 | `w_nearest_enemy_head` 3.9, `w_head_on_risk` 2.6, `w_cut_off` 2.0, `space_cap` 1.9 | `keep_distance`, `keep_repel`, `pull_radius` 0.3 |
| Survivor | 27 / 43 | 1.8 | `trap_margin` 2.0, `w_space` 1.8, `w_space_vs_length` 1.8, `w_head_on_risk` 1.5 | `pull_radius` 0.4, `w_territory` 0.5 |
| Trapper | 25 / 47 | 2.2 | `w_enemy_escape_moves` 3.2, `w_cut_off` 3.0, `w_enemy_space_after` 3.0 | `w_territory` 0.3 |
| Predictor | 35 / 56 | 1.2 | `w_expected_death` 2.8, `w_nearest_enemy_head` 2.8, `lookahead` 2.4, `w_pressure` 2.2 | `search_radius`, `w_space` 0.25 |
| Opportunist | 35 / 55 | 1.5 | `attack_threshold` 2.0, `trap_margin` 1.9, `attack_cut_off` 1.8, `attack_enemy_space_after` 1.8 | `cruise_space_vs_length` 0.5 |

Per personality:

- **Hunter.** The coach steered the search toward head-hunting terms: closing on the nearest
  enemy head, head-on risk and cutting off. It turned down the distance-keeping terms, which
  fight the Hunter's goal. Its rationales tracked single dev wins, for example "Gen-19 ... its
  touch of `w_nearest_enemy_head` alone gave the best dev win (+0.275)". Exploration rose
  from 1.2 to 1.95 to escape a plateau. Nothing passed the holdout test together with the
  guard, so the **final strategy is the hand-set Hunter**: chase the nearest head, take
  head-ons only when longer, and cut off escape routes. In the cup this was already the
  strongest play.
- **Survivor.** Its one accept, in generation 3 before the coach, let it stay closer to
  others (`keep_distance` 1, no repel term). This raised its score but also its deaths. The
  coach then favoured free-space and trap-avoidance terms (`trap_margin`, `w_space`,
  `w_space_vs_length`) and dropped `pull_radius` and `w_territory`. Generation 9 was
  its only unusable reply (empty after a retry). **Final strategy:** maximise reachable space
  relative to length, avoid traps, and no longer keep a wide berth. It wins few cup matches
  because surviving does not score points.
- **Trapper.** In generation 11, `coordinate_search` found `keep_distance` 3 → 0, which
  was accepted. The coach saw that accept, raised `coordinate_search` and the
  `keep_distance` prior, and cut the batch for one generation. When later coordinate steps
  only gave no-ops and losses, it moved back to gaussian steps. It concentrated those
  steps on the enemy-confinement terms (`w_enemy_escape_moves`, `w_cut_off`,
  `w_enemy_space_after`). **Final strategy:** approach without any distance buffer and pick
  moves that shrink rivals' escape moves and space. It won 95 cup matches after the change,
  against 40 before. On the final seeds its score gain is not significant, and it crashes into
  walls and itself more often.
- **Predictor.** The Predictor was the only lineage where the broad operators earned
  something (`archive_crossover` 0.17, `cma_es` 0.15). The coach therefore kept them less
  negative at first. Its priors went to the lookahead terms (`w_expected_death`,
  `lookahead`, `w_pressure`), then to `w_nearest_enemy_head` after the generation-26 dev
  wins. It kept exploration lowest (1.2). Nothing was accepted, so the **final strategy is the
  hand-set Predictor**: score moves by simulated expected kills and deaths a few ticks ahead.
- **Opportunist.** Its generation-3 accept halved its cruising distance (`keep_distance`
  4 → 2), and the gain held on the final seeds. The coach focused on the attack-mode terms
  (`attack_threshold`, `attack_cut_off`, `attack_enemy_space_after`) and on
  `trap_margin`, and it lowered the cruise-mode space term. **Final strategy:** cruise
  closer to rivals, and switch to attack when a rival's escape space falls below the
  threshold.

## Coach cost and reliability

| Lineage | Generations coached (9–26) | Patches applied | Cost |
|---|---|---|---|
| Hunter | 18 | 18 | $0.035 |
| Survivor | 18 | 17 | $0.042 |
| Trapper | 18 | 17 | $0.034 |
| Predictor | 18 | 18 | $0.039 |
| Opportunist | 18 | 16 | $0.054 |
| **Total** | 90 | 86 | **$0.20** |

Four replies had no usable JSON, even after the retry on empty replies that landed in
generation 11. Those applied no patch, and the harness carried on alone. A few patches,
such as the Hunter's in generations 10 and 18, came without a rationale but were applied
as usual.

The coach did change how each harness searched: the operator mix, the parameters it
touched, and the batch size. It produced **no measurable gain**. No candidate proposed
after generation 11 was accepted, so this run cannot say whether coached harnesses improve
snakes faster than uncoached ones. That would need a matched run without
`--coach-every`.

## Speed

The run was upgraded at generation boundaries. Each upgrade keeps the games identical: the
same seeds and policies give the same results.

| From gen | Change |
|---|---|
| 8 | `cma_es` joins the operators |
| 9 | CPython 3.14 (about 18% less time on a 4-game benchmark) and the coach every generation |
| 11 | coach retry on empty replies, `max_batch` cap, and the bitset `territory` race on boards up to 8,192 padded cells (12 arena games: 52.0 s and 51.6 s before, 25.2 s and 25.4 s after) |

| Generations | Evolve time | Per generation | Worker-seconds per episode | Mean cup match | Hunter wins |
|---|---|---|---|---|---|
| 1–10 | 13,157 s | ~1,316 s | 4.2–6.0 | 7,421 ticks | 87 |
| 11–26 | 11,854 s | ~741 s | 2.2–2.7 | 6,633 ticks | 117 |

Worker-seconds per episode fell by about half from generation 11. This matches the
benchmark, which played the same games at about half the time. Generation 9 alone shows no
drop from 3.14, so that 18% is a benchmark figure and is not visible in the run's noise.

## Reproduce

Run `uv run python -m arena.cli evolve --profile arena --generations 1000 --until-wins 200
--coach-every 1 --llm-provider openrouter --run-id arena-cup --workers 4`. It needs the
`llm` extra and `OPENROUTER_API_KEY`; leave out `--coach-every` for an offline run. Then run
`uv run python -m arena.cli watch --run runs/arena-cup` to watch the final champions. This
run was resumed across the upgrades above, so a fresh run is a different experiment.
