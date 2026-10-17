"""
Keep rendered evidence deterministic, fork-bound and explicit about absent observations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from test_matrix.models import Sample, write
from test_matrix.render import render

if TYPE_CHECKING:
    from pathlib import Path


def test_render_reuses_only_comparable_measurements(tmp_path: Path) -> None:
    """
    Replay identical measurements and exclude another repository's history.

    Args:
        tmp_path (Path): Disposable measurement and rendering directory.

    Returns:
        None: Replayed SVG bytes are stable and foreign history behaves like no history.
    """
    sample = Sample(1, "example/project", "a" * 40, "123-1", "scope", "b" * 64, 400, 0, 2, 4, 100, 600, 20, 400, 105, 25)
    record = tmp_path / "run.json"
    write(record, sample)
    first, second, foreign, empty = [tmp_path / name for name in ("one.svg", "two.svg", "foreign.svg", "empty.svg")]
    render([record], first, "example/project", "scope")
    render([record], second, "example/project", "scope")
    assert first.read_bytes() == second.read_bytes()
    render([record], foreign, "different/fork", "scope")
    render([], empty, "different/fork", "scope")
    assert foreign.read_bytes() == empty.read_bytes()
    assert first.read_bytes() != empty.read_bytes()
