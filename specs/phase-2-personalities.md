# Phase 2 — Personalities

**Goal:** replace the five random snakes with five snakes that each have a distinct
personality: a different objective and a different way of choosing moves. Every
personality must be **parameterized** — its behaviour comes from a small set of named
numbers — because phase 4 will let each snake tune those numbers itself.

**Out of scope:** any automatic tuning (phases 3–4). Here the parameters are set by hand.

## 1. Design: one scoring skeleton, five personalities

Every personality is a **move scorer**. Each tick, for each of the (up to) three legal
moves, it computes a set of *features*, combines them with its own *weights*, and picks
the highest-scoring move. Ties break by a fixed direction order (`UP, RIGHT, DOWN,
LEFT`), then by the snake's seeded RNG if a personality opts into random tie-breaks.

```
score(move) = Σ  weight[f] × feature_f(move, observation)
```

This keeps the personalities comparable, easy to test, and easy to tune: a phase 4
"candidate" is just a different set of numbers for the same code.

### Shared feature library (`arena/agents/features.py`)

All features are deterministic functions of `(observation, my_id, move)`:

| Feature | Meaning |
|---|---|
| `immediate_death` | 1 if the move dies this tick for certain (wall, body, own body) |
| `head_on_risk` | Probability an enemy head could also enter the target cell (enemy legal moves into it ÷ enemy legal moves) |
| `space` | Cells reachable from the new head by flood fill, capped at `space_cap`, divided by the cap |
| `space_vs_length` | 1 if reachable space ≥ own length × `trap_margin` |
| `wall_distance` | Distance from new head to the nearest wall, normalised |
| `nearest_enemy_head` | Manhattan distance to the nearest enemy head, normalised (lower = closer) |
| `enemy_space_after` | Total reachable space of nearby enemies if I move here (lower = I am squeezing them) |
| `enemy_escape_moves` | How many safe moves the nearest enemy would have after my move |
| `cut_off` | 1 if my new head sits on a cell that is in a nearby enemy's predicted path |
| `centre_distance` | Distance from the board centre, normalised |
| `straightness` | 1 if the move keeps my current heading |

Expensive features (flood fill) are bounded by `space_cap` and a search radius so a
tick stays well under the decision budget.

*As built,* one feature and three shared parameters were added while tuning, because the
table above was not enough to pass §5:

- `territory`: cells my new head reaches strictly before every enemy head (a lockstep
  breadth-first race, ties go to nobody), capped and over the cap. `space` cannot see a
  corridor an enemy will close before I get through it; in all-five matches the snakes
  kept dying in such corridors until this feature was added (deaths fell roughly
  tenfold in a small all-five comparison run).
- `keep_distance` k (int): a nearest-enemy distance d < k counts as k, so a snake pulled
  toward heads stops at k instead of pressing into head-on range.
- `keep_repel`: with it, d < k counts as `k + keep_repel × (k − d)`, so cautious snakes
  back away from a close enemy rather than idling at the floor.
- `pull_radius` r: enemies farther than r count as absent. Without it the non-hunters
  drifted toward each other from across the board and, since a chased snake's nearest
  distance is never larger than the chaser's, out-closed the Hunter on the distance
  metric (§5).

Every snake also has a small `straightness` weight (0.01): it only breaks near-ties, and
stops snakes curling in place.

### Parameters

Each personality declares a `ParamSpace`: a list of named parameters with a default, a
lower bound, an upper bound, and a type (`float` or `int`). It loads its values from a
small JSON file, `arena/agents/params/<name>.json`, so values can be changed without
touching code. Phase 4 writes new versions of exactly these files and nothing else.

```json
{ "name": "hunter", "version": 1,
  "params": { "w_immediate_death": -1000, "w_head_on_risk": -40, "w_space": 6,
              "w_nearest_enemy_head": -8, "w_cut_off": 12, "space_cap": 60,
              "search_radius": 12 } }
```

## 2. The five personalities

| # | Name | Colour | Objective | Signature behaviour |
|---|---|---|---|---|
| 0 | **Hunter** | red | Close in on enemy heads and make them run into me | Strong pull toward the nearest enemy head; tries to place its body across the enemy's path just ahead of it |
| 1 | **Survivor** | green | Die as rarely as possible; take kills when enemies blunder | Heavy weight on `space` and `wall_distance`, strong head-on avoidance; drifts toward open regions |
| 2 | **Trapper** | yellow | Shrink enemies' safe space until they have nowhere to go | Minimises `enemy_space_after` and `enemy_escape_moves`; likes to run parallel to enemies and turn across them |
| 3 | **Predictor** | blue | Out-think opponents by simulating their next move | Builds a probability map of every enemy's next head (assuming each enemy picks among its safe moves) and scores moves by expected kills minus expected death, looking `lookahead` ticks ahead |
| 4 | **Opportunist** | purple | Balance: safe by default, aggressive only when a kill is likely | Switches between a "cruise" weight set and an "attack" weight set when an enemy's escape moves drop to ≤ `attack_threshold` |

*As built* (version 1 params in `arena/agents/params/`):

| Name | Main weights | Shared params |
|---|---|---|
| Hunter | `nearest_enemy_head` −30, `cut_off` 12, `head_on_risk` −40, `territory` 20, `space_vs_length` 20, `space` 6 | `keep_distance` 1 |
| Survivor | `head_on_risk` −100, `territory` 40, `space_vs_length` 40, `space` 20, `nearest_enemy_head` −8, `enemy_escape_moves` −3, `wall_distance` 1 | `keep_distance` 3, `keep_repel` 1, `pull_radius` 15 |
| Trapper | `enemy_space_after` −15, `enemy_escape_moves` −10, `nearest_enemy_head` −20, `cut_off` 4, `head_on_risk` −40, `territory` 20, `space_vs_length` 20, `space` 6 | same as Survivor |
| Predictor | `w_expected_kills` 300, `w_pressure` 10, `w_expected_death` −300, `lookahead` 2, `discount` 0.5, plus `nearest_enemy_head` −20, `territory` 20, `space_vs_length` 20, `space` 6 | same as Survivor |
| Opportunist | cruise: `head_on_risk` −100, `territory` 30, `space_vs_length` 30, `space` 15, `nearest_enemy_head` −20; attack: Trapper-like squeeze weights; `attack_threshold` 1 | `keep_distance` 4, `keep_repel` 1, `pull_radius` 15 |

Changes from the sketch above, and why:

- Survivor's `wall_distance` weight is small (1), not heavy: a strong pull to the centre
  packed it into the middle of the board with everyone else. Opportunist's cruise set
  dropped `wall_distance` for the same reason: snakes clustered in the centre sat closer
  to each other than the Hunter sat to them, failing the enemy-distance check (§5).
- Every non-hunter has a positive `nearest_enemy_head` pull limited by `pull_radius` 15
  and `keep_distance` with `keep_repel`: it lets them take kills when an enemy blunders
  nearby (§5 asks each to out-kill RandomSafe) without seeking enemies out.

All five start from the same `immediate_death` weight (a large negative) so none of them
is suicidal on day one. Everything else is personality-specific.

Personalities are **starting points, not cages**: phase 4 may move any weight anywhere in
its bounds, and a Survivor that learns to hunt is a legitimate result.

## 3. Measuring personality

To check the five are actually different, the tournament runner reports per snake:

- kills per 1,000 alive ticks, deaths per 1,000 alive ticks, K/D
- mean distance to nearest enemy head (aggression)
- mean reachable space (caution)
- share of own deaths by cause (wall / self / body / head-on / head-swap)
- 5 × 5 kill matrix (who killed whom)

## 4. Arena density check

Phase 1 measures kills per 1,000 ticks with random snakes on 100 × 100. If phase 2 snakes
still produce so few kills that a first-to-100 match takes more than ~50,000 ticks on
average, record that number and evaluate on a smaller board (for example 50 × 50) for
experiments, clearly labelled. Never silently change the default rules to make numbers
look better.

## 5. Acceptance criteria

- Each personality is one module + one params JSON, implements the `Policy` protocol, and
  is deterministic given the match seed.
- Every personality respects a decision budget of 5 ms median and 20 ms p99 per move on a
  100 × 100 board (measured by `arena.cli bench --policies all`).
- In a 100-match tournament of all five personalities, **every** personality has fewer
  deaths per 1,000 alive ticks than `RandomSafe` playing in the same seat mix.
- In a 100-match tournament of each personality against four `RandomSafe` snakes, every
  personality has a higher mean kills per 1,000 ticks than the `RandomSafe` average, with
  a 95% bootstrap interval that excludes zero.
- The behaviour metrics in §3 show the personalities differ: Hunter has the lowest mean
  distance to enemy heads, Survivor the highest mean reachable space and fewest deaths.
  If a personality fails its own signature, adjust its hand-set weights (that is
  allowed in this phase) and record the change.
- The viewer shows each snake's name and colour instead of `s0`…`s4`.
