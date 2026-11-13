from dataclasses import replace
from pathlib import Path

from evo_helpers import TINY, tiny_evolution

from arena.evolution import cup
from arena.evolution.entrants import Entrant, hand_set
from arena.evolution.run import PROFILES, STRATEGY_PRIORS, Profile, lineage_proposer
from arena.rsi.harness import AdaptiveHarness

SMALL = cup.CupSettings(width=14, height=14, length=4, target=2, max_ticks=600, matches=3)


def champions() -> dict[str, Entrant]:
    return {n: Entrant.personality(n, hand_set(n), 1) for n in ("hunter", "predictor")}


def test_cup_matches_are_seeded_and_seat_shuffled() -> None:
    tasks = cup.cup_tasks(SMALL, 0, 1, champions())
    assert tasks == cup.cup_tasks(SMALL, 0, 1, champions())
    assert tasks != cup.cup_tasks(SMALL, 0, 2, champions())
    assert all(sorted(t.names) == ["hunter", "predictor", "random"] for t in tasks)
    assert len({t.names for t in tasks}) > 1
    played = [cup.play_cup_match(t) for t in tasks]
    assert played == [cup.play_cup_match(t) for t in tasks]
    assert all(set(m["scores"]) == {"hunter", "predictor", "random"} for m in played)


def test_standings_count_wins() -> None:
    recs = [{"matches": [{"winner": "hunter"}, {"winner": None}, {"winner": "hunter"}]}]
    wins = cup.standings(recs)
    assert wins["hunter"] == 2 and wins["random"] == 0
    assert cup.format_standings(wins, ["predictor", "hunter"]).startswith("hunter 2")


def test_evolution_plays_the_cup_and_stops_on_wins(tmp_path: Path) -> None:
    profile = replace(TINY, cup=SMALL, patience=None)
    result = tiny_evolution(tmp_path, generations=50, profile=profile, until_wins=2).run()
    records = cup.read_cup(tmp_path)
    assert [r["generation"] for r in records] == list(range(1, result.generations + 1))
    leader, wins = cup.standings(records).most_common(1)[0]
    assert wins >= 2 and result.stop_reason == f"{leader} reached {wins} cup wins"
    again = tiny_evolution(tmp_path, generations=50, profile=profile, until_wins=2).run()
    assert again.generations == result.generations
    assert len(cup.read_cup(tmp_path)) == len(records)


def test_profiles_round_trip_and_arena_uses_the_harness() -> None:
    for p in PROFILES.values():
        assert Profile.from_dict(p.to_dict()) == p
    arena = PROFILES["arena"]
    assert arena.cup is not None and arena.patience is None
    h = lineage_proposer(arena, "trapper")
    assert isinstance(h, AdaptiveHarness)
    assert h.priors == STRATEGY_PRIORS["trapper"]
