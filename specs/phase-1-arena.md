# Phase 1 — The Arena

**Goal:** a correct, deterministic five-snake battle engine with two ways to run it:
a fast **simulation mode** (headless, no rendering) and a **visualization mode** (watch a
match live or replay a saved one). In this phase every snake is a simple random AI.

**Out of scope for this phase:** personalities (phase 2), any self-improvement
(phases 3–4), accounts, networking between humans, LLMs.

## 1. Rules (defaults; all configurable in one `GameConfig`)

| Setting | Default | Notes |
|---|---|---|
| Board | 150 × 150, bounded, no wrap | `(0,0)` is top-left; `x` grows right, `y` grows down |
| Snakes | 5 persistent identities | ids `s0`…`s4` until phase 2 names them; configurable 1–8 |
| Snake length | Fixed **10** cells, no growth | configurable 3–10 |
| Directions | `UP`, `DOWN`, `LEFT`, `RIGHT` | a 180° reversal is treated as "continue straight" |
| Movement | Simultaneous: every alive snake moves one cell per tick | |
| Spawn | Seeded random straight run of `length` empty cells, with clearance | see §3 |
| Respawn delay | 10 ticks after death | retried every tick until a safe spot exists |
| Score | +1 per credited kill, −1 per self-inflicted death (wall or self) | other deaths cost no points; the penalty is configurable (`self_death_penalty`, default 1, 0 turns it off) |
| Win | First snake to **100 points** (score) | checked at the end of each tick |
| Tick cap | 100,000 ticks | safety net; the match then ends by ranking (§5) |

The win target and the tick cap are both configurable so tests and experiments can use
short matches. The viewer defaults to a 30 × 30 board and first to 10 points (§9), because
random snakes on 150 × 150 almost never reach 100 points before the cap (§10).

## 2. One tick, step by step

The engine exposes a pure function:

```python
step(state: GameState, actions: Mapping[SnakeId, Direction]) -> tuple[GameState, list[Event]]
```

`step` never mutates its input and never reads a clock or global RNG. The only
randomness is the `rng_state` stored inside `GameState`, used for spawning.

1. **Collect actions.** Every alive snake chooses from the *same* immutable snapshot of
   the start-of-tick state. Nobody sees anyone else's choice. Missing or invalid actions,
   errors and timeouts fall back to "continue straight", and an `ActionFallback` event is
   logged.
2. **Resolve reversals.** A move straight back into the neck becomes "continue straight".
3. **Compute intended heads.** `new_head = head + direction`.
4. **Remove tails.** Because length is fixed, every moving snake vacates its tail cell.
   The *collision snapshot* is: all alive snakes' bodies **minus their tails**, plus
   nothing else. (Heads are already in the bodies.)
5. **Find deaths, all from the same snapshot, independent of iteration order:**
   - **Wall:** new head is off the board. No kill credit; the snake loses a point.
   - **Head-on:** two or more new heads land on the same cell. All of them die. No kill
     credit.
   - **Head-swap:** A's new head is B's old head and B's new head is A's old head. Both
     die. No kill credit.
   - **Self:** new head lands on the snake's own snapshot body. No kill credit; the snake
     loses a point.
   - **Body:** new head lands on another snake B's snapshot body. The mover dies and
     **B gets +1 kill — even if B also dies this same tick.**
   - A snake can die from more than one cause in one tick; it dies once. A cell in the
     snapshot has at most one owner, so a head can hit at most one body. If any cause is
     a body hit, the death's `cause` is `body` and that body's owner is credited (for
     example, two heads meeting on a cell of C's body are both credited to C).
   - One owner earns one point **per distinct victim** in a tick.
   - Moving into a tail cell vacated this tick is **safe** unless another rule applies
     (for example another head also moves there).
6. **Commit.** Remove all dead snakes together. Survivors' bodies become
   `[new_head] + body[:-1]`.
7. **Respawn bookkeeping.** Decrement every dead snake's respawn counter. Snakes whose
   counter reaches 0 try to spawn (§3). Spawning happens only after collisions are
   resolved, so a snake can never spawn and collide in the same tick.
8. **Check for a winner** (§5) and emit events.

### Events

Every tick produces a list of plain, serialisable events:

- `Death(tick, victim, killer | None, cause)` where `cause` is one of `wall`, `self`,
  `body`, `head_on`, `head_swap`.
- `Kill(tick, killer, victim)` — exactly one per credited body death.
- `Spawn(tick, snake, life_id, cells, heading)`
- `ActionFallback(tick, snake, reason)`
- `MatchEnd(tick, reason, standings)` where `reason` is `score_target` or `tick_cap`.

Scores are **derived from events only**. A replay re-computes scores from its event list
and must match the engine's final scores exactly.

## 3. Spawning

- Each spawn draws from the seeded RNG: a random cell and a random direction, and lays a
  straight run of `length` cells behind the head.
- **Valid** means: every cell is on the board, none is occupied by a living snake, and
  there is a clearance margin of 2 empty cells around the run and 3 cells ahead of the
  head (so a snake never spawns facing a wall or a body it cannot avoid).
- Try up to 100 random attempts, then fall back to a deterministic scan of the board in
  row-major order. If nothing fits, the snake stays dead and retries next tick. Spawning
  never crashes.
- Each spawn gets a new `life_id`; the snake keeps its identity and cumulative score.
- At match start all five snakes spawn on tick 0 in id order using the same procedure.

## 4. What a policy sees

```python
@dataclass(frozen=True)
class SnakeView:
    id: SnakeId
    alive: bool
    body: tuple[Cell, ...]        # head first; empty when dead
    heading: Direction | None
    kills: int
    deaths: int
    respawn_in: int               # 0 when alive

@dataclass(frozen=True)
class Observation:
    tick: int
    width: int
    height: int
    self_id: SnakeId
    snakes: tuple[SnakeView, ...] # all five, in id order

class Policy(Protocol):
    name: str
    def reset(self, seed: int) -> None: ...
    def choose_action(self, obs: Observation) -> Direction: ...
```

Policies get full visibility of the board but never see the RNG, other policies'
choices, or other policies' code. A policy that needs randomness gets its own seeded
`random.Random` in `reset`, derived from the match seed and its snake id.

## 5. Ending a match and ranking

- The match ends at the end of the first tick in which any snake has ≥ 100 kills, or at
  the tick cap.
- Several snakes may cross 100 on the same tick; rank them all by the tie-breakers.
- **Ranking:** most kills → fewest deaths → most alive ticks → shared rank.

## 6. The random baseline policy (`RandomSafe`)

The only snake brain in phase 1. Each tick it lists the three non-reversing moves, drops
any that obviously die *right now* (wall, any body cell in the start-of-tick snapshot
except tails that will move), and picks uniformly from what's left using its seeded RNG.
If no move is safe it continues straight. A pure `RandomUniform` policy (no safety check)
also exists as a control.

## 7. Simulation mode (headless)

```bash
python -m arena.cli run-match --seed 42 [--width 150 --height 150 --length 10 \
    --target 100 --max-ticks 100000] [--replay out/match-42.json]
python -m arena.cli run-tournament --matches 100 --seed-start 0 --out out/tournament/
```

- `run-match` prints final standings (kills, deaths, K/D, alive ticks, rank) and the
  match end reason.
- `run-tournament` runs N seeds, writes per-match results as JSONL and a summary CSV
  (per snake: wins, mean kills, mean deaths, kills per 1,000 ticks), plus a 5 × 5
  "who killed whom" matrix.
- Match runs can be spread over processes; results must not depend on how many.

## 8. Replays

A replay is a JSON file:

```json
{
  "schema_version": 1,
  "engine_version": "0.1.0",
  "config": { "...": "..." },
  "seed": 42,
  "policies": { "s0": {"name": "RandomSafe", "version": "1", "hash": "..."} },
  "initial_state": { "...": "..." },
  "actions": [["UP", "LEFT", "LEFT", "DOWN", "RIGHT"], "..."],
  "events": [ "..." ],
  "final_standings": [ "..." ]
}
```

Re-simulating `initial_state` with the stored `actions` (no policies needed) must
reproduce the stored events exactly. Replays are how the viewer shows past matches.

## 9. Visualization mode

```bash
python -m arena.cli watch --seed 42            # live match, opens the viewer
python -m arena.cli watch --replay out/match-42.json
```

- A single static page (`arena/viz/static/index.html`, plain HTML + Canvas + JS, no build
  step) served by a tiny standard-library HTTP server. The page fetches frames in order
  in chunks (`GET /api/match/<id>/frames?from=N&count=K`); the server computes ticks only
  when asked. (This replaced the earlier Server-Sent Events idea: pull-based chunks make
  pause and speed purely client-side.) Replay mode re-runs a replay's stored actions.
- Settings form: seed, board size, snake count and length, points to win (default 10),
  respawn delay, tick cap, self-death penalty and policy (default `arena`: the five
  personalities plus one `random_safe` snake). "Finish now" runs the match to the end instantly.
  Replays can be downloaded from a live match and loaded back.
- Dark board, five clearly different colours, a distinct head marker, smooth
  interpolation between ticks.
- Side panel leaderboard (sorted by score): snake, score, kills, deaths, K/D, current life length, respawn
  countdown.
- Kill feed: `s2 eliminated s4`; head-on crashes show `s1 × s3 — head-on, no killer`.
- Controls: play/pause, step one tick, speed 1× / 2× / 5× / 10× / 50× / max, start, new seed.
- **Speed and pause only change playback.** The live server computes ticks on demand at
  the requested rate; the result of a seed never depends on how fast it was watched.
- Base rate: 10 ticks per second at 1×; the page opens at 5× (50 ticks/s).

## 10. Performance

- Target: ≥ 20,000 ticks/second for the engine alone with five `RandomSafe` snakes on a
  typical laptop, single process. Measure it with `python -m arena.cli bench` and record
  the real number in the README. If the target isn't met, document the gap rather than
  hide it.
- The 150 × 150 board with five 10-cell snakes is sparse; expect few kills per 1,000
  ticks with random play. Measure and record it — phase 2 depends on that number.

## 11. Acceptance tests (all automated)

- **Determinism:** same seed + same policies + same config ⇒ identical event list and
  standings, across runs and across process counts.
- **Shape invariant:** every alive snake has exactly `length` unique, 4-connected cells,
  all on the board, after every tick of 10,000-tick random matches on many seeds.
- **Movement:** a head moves exactly one cell per tick and never reverses.
- **Wall:** moving off the board kills, no credit, −1 point.
- **Self:** running into your own body kills, no credit, −1 point.
- **Body:** A hits B's body ⇒ A dies, B +1.
- **Simultaneous credit:** A hits B's body while B hits a wall the same tick ⇒ both die,
  B still gets +1.
- **Multi-victim:** two snakes hit B's body in the same tick ⇒ B gets +2.
- **Head-on:** two heads into one cell ⇒ both die, nobody credited. Same for three.
- **Head-swap:** two heads swap cells ⇒ both die, nobody credited.
- **Vacated tail:** following directly behind a tail (or your own tail) is safe.
- **Tail race:** a tail cell vacated this tick that two heads both enter ⇒ head-on rule.
- **Respawn:** a dead snake reappears after exactly 10 ticks when there's room, with a new
  `life_id` and the same cumulative score; with no room it retries without crashing.
- **Spawn safety:** no spawn overlaps a living snake or breaks the clearance rule.
- **Win:** the match ends on the tick a snake reaches the target; ties are ranked by the
  tie-breakers.
- **Replay:** re-simulating a saved replay reproduces its events and scores exactly.
