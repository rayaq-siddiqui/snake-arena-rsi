"""The README system-design diagram must name every module under arena/."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def diagram() -> str:
    text = (ROOT / "README.md").read_text()
    start = text.index("<!-- system-design:start -->")
    end = text.index("<!-- system-design:end -->")
    return text[start:end]


def test_every_module_is_in_the_system_design_diagram() -> None:
    block = diagram()
    arena = ROOT / "arena"
    missing = [
        str(p.relative_to(arena))
        for p in sorted(arena.rglob("*.py"))
        if p.name != "__init__.py" and str(p.relative_to(arena)) not in block
    ]
    assert not missing, f"add these modules to the README system-design diagram: {missing}"


def test_every_static_viewer_file_is_in_the_diagram() -> None:
    block = diagram()
    static = ROOT / "arena" / "viz" / "static"
    assert all(p.name in block for p in static.iterdir() if p.is_file())
