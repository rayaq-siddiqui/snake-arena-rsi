from pathlib import Path
from typing import Any

from arena.evolution.evaluator import EvalSettings
from arena.evolution.run import Evolution, Profile

TINY = Profile(
    "tiny",
    EvalSettings(12, 12, 80),
    dev_pairs=3,
    holdout_pairs=3,
    holdout_blocks=2,
    final_pairs=3,
    dev_pool=40,
    patience=3,
    resamples=200,
)


def tiny_evolution(run_dir: Path, generations: int = 2, **kw: Any) -> Evolution:
    kw.setdefault("workers", 1)
    kw.setdefault("lineages", ("hunter", "predictor"))
    return Evolution(run_dir, kw.pop("profile", TINY), generations, **kw)


def lineage_files(run_dir: Path, name: str = "generations.jsonl") -> dict[str, str]:
    return {p.parent.name: p.read_text() for p in sorted((run_dir / "lineages").glob(f"*/{name}"))}
