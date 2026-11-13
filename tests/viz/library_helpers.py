from pathlib import Path

from arena.agents import make_policy
from arena.engine import GameConfig
from arena.sim.match import Match, simulate_match
from arena.sim.replay import build_replay, save_replay
from arena.sim.tournament import write_outputs

SMALL = GameConfig(width=12, height=12, snake_length=5, score_target=2, max_ticks=400)
LINEUP = ["hunter", "survivor", "trapper", "predictor", "opportunist"]


def make_library(root: Path) -> None:
    for seed in (1, 2):
        match = Match([make_policy("random_safe") for _ in range(5)], seed, SMALL, record=True)
        match.run()
        save_replay(build_replay(match), root / "replays" / f"seed-{seed}.json")
    results = [simulate_match([make_policy(n) for n in LINEUP], seed, SMALL) for seed in (3, 4, 5)]
    write_outputs(root / "tournament", results)
    (root / "tournament" / "config.json").write_text('{"not": "a replay"}')
    (root / "lineages").mkdir()
    save_replay(build_replay(match), root / "lineages" / "skipped.json")
