import ast
from pathlib import Path

import arena.rsi

FORBIDDEN = ("arena.engine", "arena.agents", "arena.sim", "arena.viz", "arena.evolution")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise AssertionError(f"{path.name}: use absolute imports")
            names.add(node.module or "")
    return names


def test_rsi_knows_nothing_about_snakes() -> None:
    root = Path(arena.rsi.__file__).parent
    files = sorted(root.rglob("*.py"))
    assert files
    for f in files:
        bad = [m for m in imported_modules(f) if m.startswith(FORBIDDEN) or m == "arena"]
        assert not bad, f"{f.name} imports {bad}"
