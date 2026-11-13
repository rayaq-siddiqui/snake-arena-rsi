import pytest

from arena.engine import GameConfig
from arena.sim.boards import BOARDS, board


def test_default_board_is_the_specified_game() -> None:
    assert board("default") == GameConfig()


def test_experiment_board_only_shrinks_the_board() -> None:
    exp = board("experiment")
    assert (exp.width, exp.height) == (50, 50)
    assert exp.to_dict() | {"width": 150, "height": 150} == GameConfig().to_dict()


def test_unknown_boards_are_rejected() -> None:
    with pytest.raises(ValueError, match="unknown board"):
        board("tiny")
    assert set(BOARDS) == {"default", "experiment"}
