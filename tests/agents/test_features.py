import pytest
from board_helpers import line, observe

from arena.agents.features import (
    board_of,
    centre_distance,
    cut_off,
    enemy_escape_moves,
    enemy_space_after,
    flood_fill,
    head_on_risk,
    immediate_death,
    nearest_enemy_head,
    space,
    space_vs_length,
    straightness,
    wall_distance,
)

P: dict[str, float] = {}


def test_immediate_death_covers_walls_and_bodies() -> None:
    board = board_of(
        observe({"s0": line((0, 5), "RIGHT"), "s1": line((0, 4), "UP"), "s2": line((9, 9), "UP")})
    )
    assert immediate_death(board, "s0", "LEFT", P) == 1.0
    assert immediate_death(board, "s0", "UP", P) == 1.0
    assert immediate_death(board, "s0", "DOWN", P) == 0.0


def test_head_on_risk_is_the_enemy_share_of_moves_into_the_cell() -> None:
    board = board_of(observe({"s0": line((5, 5), "DOWN"), "s1": line((6, 4), "RIGHT")}))
    assert head_on_risk(board, "s0", "UP", P) == pytest.approx(1 / 3)
    assert head_on_risk(board, "s0", "RIGHT", P) == pytest.approx(1 / 3)
    assert head_on_risk(board, "s0", "LEFT", P) == 0.0


def test_head_on_risk_combines_several_enemies() -> None:
    board = board_of(
        observe(
            {
                "s0": line((5, 5), "DOWN"),
                "s1": line((4, 4), "LEFT"),
                "s2": line((6, 4), "RIGHT"),
            }
        )
    )
    assert head_on_risk(board, "s0", "UP", P) == pytest.approx(1 - (2 / 3) ** 2)


def pocket_board():  # type: ignore[no-untyped-def]
    return board_of(observe({"s0": line((1, 0), "RIGHT"), "s1": line((0, 1), "DOWN")}))


def test_space_counts_reachable_cells_up_to_the_cap() -> None:
    board = pocket_board()
    assert space(board, "s0", "LEFT", P) == pytest.approx(1 / 60)
    assert space(board, "s0", "DOWN", P) == 1.0
    assert space(board, "s0", "UP", P) == 0.0


def test_space_vs_length_flags_pockets_smaller_than_the_margin() -> None:
    board = pocket_board()
    assert space_vs_length(board, "s0", "LEFT", P) == 0.0
    assert space_vs_length(board, "s0", "DOWN", P) == 1.0


def test_flood_fill_stays_inside_its_radius() -> None:
    board = board_of(observe({"s0": line((10, 10), "DOWN")}, size=40))
    assert flood_fill(board, [(20, 20)], cap=10_000, radius=2) == 13


def test_wall_distance_is_zero_at_the_wall_and_one_at_the_centre() -> None:
    board = board_of(observe({"s0": line((1, 10), "RIGHT"), "s1": line((9, 9), "DOWN")}, size=21))
    assert wall_distance(board, "s0", "LEFT", P) == 0.0
    assert wall_distance(board, "s1", "UP", P) == pytest.approx(0.8)
    assert wall_distance(board, "s1", "RIGHT", P) == pytest.approx(0.9)


def test_nearest_enemy_head_is_normalised_distance() -> None:
    board = board_of(observe({"s0": line((5, 5), "DOWN"), "s1": line((5, 0), "LEFT")}))
    assert nearest_enemy_head(board, "s0", "UP", P) == pytest.approx(4 / 40)
    assert nearest_enemy_head(board, "s0", "LEFT", P) == pytest.approx(6 / 40)
    alone = board_of(observe({"s0": line((5, 5), "DOWN")}))
    assert nearest_enemy_head(alone, "s0", "UP", P) == 1.0


def test_enemy_escape_moves_counts_what_my_head_takes_away() -> None:
    board = board_of(observe({"s0": line((6, 1), "DOWN"), "s1": line((5, 0), "LEFT")}))
    assert enemy_escape_moves(board, "s0", "UP", P) == pytest.approx(1 / 3)
    assert enemy_escape_moves(board, "s0", "LEFT", P) == pytest.approx(1 / 3)
    assert enemy_escape_moves(board, "s0", "RIGHT", P) == pytest.approx(2 / 3)
    alone = board_of(observe({"s0": line((6, 1), "DOWN")}))
    assert enemy_escape_moves(alone, "s0", "UP", P) == 1.0


def test_enemy_space_after_drops_when_i_plug_the_exit() -> None:
    bodies = {"s0": line((2, 1), "DOWN"), "s1": line((0, 1), "DOWN"), "s2": line((1, 5), "UP")}
    board = board_of(observe(bodies))
    plugged = enemy_space_after(board, "s0", "UP", P)
    open_ = enemy_space_after(board, "s0", "RIGHT", P)
    assert open_ - plugged > 0.45
    alone = board_of(observe({"s0": line((2, 1), "DOWN")}))
    assert enemy_space_after(alone, "s0", "UP", P) == 1.0


def test_cut_off_marks_cells_on_an_enemy_path() -> None:
    board = board_of(observe({"s0": line((8, 11), "DOWN"), "s1": line((5, 10), "LEFT")}))
    assert cut_off(board, "s0", "UP", P) == 1.0
    assert cut_off(board, "s0", "LEFT", P) == 0.0


def test_centre_distance_and_straightness() -> None:
    board = board_of(observe({"s0": line((10, 10), "DOWN")}, size=21))
    assert centre_distance(board, "s0", "UP", P) == pytest.approx(1 / 20)
    assert straightness(board, "s0", "UP", P) == 1.0
    assert straightness(board, "s0", "LEFT", P) == 0.0


def test_board_is_shared_within_a_tick() -> None:
    obs = observe({"s0": line((10, 10), "DOWN")})
    assert board_of(obs) is board_of(obs)
