from arena.agents import make_policy
from arena.engine import GameConfig, GameState, SnakeState
from arena.sim.match import Match
from arena.sim.metrics import SPACE_CAP, SPACE_RADIUS, Behaviour, sample
from arena.sim.tournament import run_matches, summarise


def two_snakes() -> GameState:
    config = GameConfig(width=10, height=10, num_snakes=2, snake_length=3)
    snakes = (
        SnakeState("s0", ((2, 2), (2, 3), (2, 4)), "UP", True),
        SnakeState("s1", ((6, 2), (6, 3), (6, 4)), "UP", True),
    )
    return GameState(config, snakes, rng_state=1)


def test_sample_measures_enemy_distance_and_reachable_space() -> None:
    totals = {"s0": Behaviour(), "s1": Behaviour()}
    sample(two_snakes(), totals)
    assert totals["s0"].mean_enemy_distance == 4
    # Cells within SPACE_RADIUS of the cell straight ahead, (2, 1), minus non-tail body cells
    # (tails move away next tick).
    blocked = {(2, 2), (2, 3), (6, 2), (6, 3)}
    within = {
        (x, y)
        for x in range(10)
        for y in range(10)
        if abs(x - 2) + abs(y - 1) <= SPACE_RADIUS and (x, y) not in blocked
    }
    assert totals["s0"].mean_space == len(within) <= SPACE_CAP
    sample(two_snakes(), totals)
    assert totals["s0"].distance_samples == 2 and totals["s0"].mean_enemy_distance == 4


def test_matches_sample_behaviour_only_when_asked() -> None:
    config = GameConfig(width=20, height=20, max_ticks=200)
    off = Match([make_policy("random_safe") for _ in range(5)], 1, config).run()
    on = Match([make_policy("random_safe") for _ in range(5)], 1, config, metrics_every=10).run()
    assert all(b.space_samples == 0 for b in off.behaviour.values())
    assert sum(b.space_samples for b in on.behaviour.values()) > 0
    assert on.standings == off.standings


def test_summary_reports_rates_behaviour_and_death_shares() -> None:
    config = GameConfig(width=16, height=16, max_ticks=1500, score_target=10**6)
    results = list(run_matches(["random_uniform"] * 5, range(3), config))
    row = summarise(results)[0].row()
    for key in ("kills_per_1000_alive", "deaths_per_1000_alive", "mean_enemy_distance"):
        assert key in row
    assert isinstance(row["mean_space"], float) and row["mean_space"] > 0
    shares = [row[f"death_share_{c}"] for c in ("wall", "self", "body", "head_on", "head_swap")]
    assert abs(sum(shares) - 1) < 1e-3
