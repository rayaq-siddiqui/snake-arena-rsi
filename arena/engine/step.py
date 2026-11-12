"""The pure tick function and match start (phase 1 spec, sections 2-5)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from arena.engine.rng import derive_seed
from arena.engine.spawn import find_spawn
from arena.engine.types import (
    DELTAS,
    OPPOSITE,
    ActionFallback,
    Cell,
    Death,
    DeathCause,
    Direction,
    EndReason,
    Event,
    GameConfig,
    GameState,
    Kill,
    MatchEnd,
    SnakeId,
    SnakeState,
    Spawn,
    Standing,
    as_direction,
)


def new_game(config: GameConfig, seed: int) -> tuple[GameState, list[Event]]:
    """Create tick 0: every snake spawns in id order from the seeded RNG."""
    rng_state = derive_seed(seed, "engine")
    occupied: set[Cell] = set()
    snakes: list[SnakeState] = []
    events: list[Event] = []
    for snake_id in config.snake_ids:
        snake = SnakeState(id=snake_id)
        rng_state, cells, heading = find_spawn(rng_state, config, occupied)
        if cells is not None and heading is not None:
            snake = _spawned(snake, cells, heading)
            occupied.update(cells)
            events.append(Spawn(0, snake_id, snake.life_id, cells, heading))
        snakes.append(snake)
    return GameState(config=config, snakes=tuple(snakes), rng_state=rng_state), events


def resolve_direction(snake: SnakeState, action: object) -> Direction:
    """Apply the no-reversal rule: invalid or reversing actions continue straight."""
    assert snake.heading is not None
    direction = as_direction(action)
    if direction is None or direction == OPPOSITE[snake.heading]:
        return snake.heading
    return direction


def step(state: GameState, actions: Mapping[SnakeId, object]) -> tuple[GameState, list[Event]]:
    """Advance one tick. Pure: never mutates ``state`` and reads no global state."""
    if state.finished:
        raise ValueError("match is already finished")
    config = state.config
    tick = state.tick + 1
    events: list[Event] = []
    alive = [s for s in state.snakes if s.alive]

    directions: dict[SnakeId, Direction] = {}
    new_heads: dict[SnakeId, Cell] = {}
    for s in alive:
        raw = actions.get(s.id)
        heading = s.heading
        assert heading is not None
        chosen = as_direction(raw)
        if chosen is None:
            events.append(ActionFallback(tick, s.id, "missing" if raw is None else "invalid"))
            d = heading
        else:
            d = heading if chosen == OPPOSITE[heading] else chosen
        directions[s.id] = d
        dx, dy = DELTAS[d]
        new_heads[s.id] = (s.body[0][0] + dx, s.body[0][1] + dy)

    owner: dict[Cell, SnakeId] = {}
    for s in alive:
        for cell in s.body[:-1]:
            owner[cell] = s.id

    head_count: dict[Cell, int] = {}
    for cell in new_heads.values():
        head_count[cell] = head_count.get(cell, 0) + 1

    old_heads = {s.id: s.body[0] for s in alive}
    swapped: set[SnakeId] = set()
    for a in alive:
        for b in alive:
            if (
                a.id < b.id
                and new_heads[a.id] == old_heads[b.id]
                and new_heads[b.id] == old_heads[a.id]
            ):
                swapped.update((a.id, b.id))

    deaths: dict[SnakeId, tuple[DeathCause, SnakeId | None]] = {}
    w, h = config.width, config.height
    for s in alive:
        x, y = cell = new_heads[s.id]
        if not (0 <= x < w and 0 <= y < h):
            deaths[s.id] = ("wall", None)
        elif s.id in swapped:
            deaths[s.id] = ("head_swap", None)
        elif cell in owner:
            other = owner[cell]
            deaths[s.id] = ("self", None) if other == s.id else ("body", other)
        elif head_count[cell] > 1:
            deaths[s.id] = ("head_on", None)

    kills: dict[SnakeId, int] = {}
    for victim, (cause, killer) in deaths.items():
        events.append(Death(tick, victim, killer, cause, new_heads[victim]))
        if killer is not None:
            events.append(Kill(tick, killer, victim))
            kills[killer] = kills.get(killer, 0) + 1

    occupied: set[Cell] = set()
    committed: list[SnakeState] = []
    to_spawn: list[int] = []
    for s in state.snakes:
        gained = kills.get(s.id, 0)
        if s.alive and s.id in deaths:
            s = SnakeState(
                s.id,
                (),
                s.heading,
                False,
                s.life_id,
                s.kills + gained,
                s.deaths + 1,
                config.respawn_delay,
                s.alive_ticks,
                0,
            )
        elif s.alive:
            body = (new_heads[s.id], *s.body[:-1])
            occupied.update(body)
            s = SnakeState(
                s.id,
                body,
                directions[s.id],
                True,
                s.life_id,
                s.kills + gained,
                s.deaths,
                0,
                s.alive_ticks + 1,
                s.life_ticks + 1,
            )
        else:
            if gained or s.respawn_in:
                s = replace(s, kills=s.kills + gained, respawn_in=max(0, s.respawn_in - 1))
            if s.respawn_in == 0:
                to_spawn.append(len(committed))
        committed.append(s)

    rng_state = state.rng_state
    for index in to_spawn:
        s = committed[index]
        rng_state, cells, heading = find_spawn(rng_state, config, occupied)
        if cells is None or heading is None:
            continue
        s = _spawned(s, cells, heading)
        occupied.update(cells)
        committed[index] = s
        events.append(Spawn(tick, s.id, s.life_id, cells, heading))

    snakes = tuple(committed)
    finished = False
    end_reason: EndReason | None = None
    if any(s.kills >= config.score_target for s in snakes):
        finished, end_reason = True, "score_target"
    elif tick >= config.max_ticks:
        finished, end_reason = True, "tick_cap"
    if end_reason is not None:
        events.append(MatchEnd(tick, end_reason, rank(snakes)))
    next_state = GameState(
        config=config,
        snakes=snakes,
        rng_state=rng_state,
        tick=tick,
        finished=finished,
        end_reason=end_reason,
    )
    return next_state, events


def rank(snakes: tuple[SnakeState, ...]) -> tuple[Standing, ...]:
    """Most kills, then fewest deaths, then most alive ticks; exact ties share a rank."""

    def key(s: SnakeState) -> tuple[int, int, int]:
        return (-s.kills, s.deaths, -s.alive_ticks)

    ordered = sorted(snakes, key=lambda s: (key(s), s.id))
    standings: list[Standing] = []
    for i, s in enumerate(ordered):
        position = standings[-1].rank if i > 0 and key(s) == key(ordered[i - 1]) else i + 1
        standings.append(Standing(s.id, position, s.kills, s.deaths, s.alive_ticks))
    return tuple(standings)


def _spawned(snake: SnakeState, cells: tuple[Cell, ...], heading: Direction) -> SnakeState:
    return replace(
        snake,
        body=cells,
        heading=heading,
        alive=True,
        life_id=snake.life_id + 1,
        respawn_in=0,
        life_ticks=0,
    )
