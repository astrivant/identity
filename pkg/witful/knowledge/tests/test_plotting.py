"""
Exercise deterministic rendering at the empty and populated collection boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from witful.knowledge.models import Discipline, Identity, Skill
from witful.knowledge.plotting import write_plots

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("populated", [False, True])
def test_plots_preserve_unchanged_bytes_and_modification_times(tmp_path: Path, populated: bool) -> None:
    """
    Render repeatable artifacts without inventing application history for either collection size.

    Args:
        tmp_path (Path): Isolated output directory.
        populated (bool): Whether to include a skill and discipline.

    Returns:
        None: Six nonempty assets reproduce exactly and retain their modification times.
    """
    disciplines = (Discipline("d", "Design", (Skill("s", "Contracts"),)),) if populated else ()
    model = Identity("root", "Example", disciplines)
    paths = write_plots(model, (), tmp_path)
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    assert len(paths) == 6
    assert 'id="plot-heading"' in (tmp_path / "knowledge-map.svg").read_text()
    if populated:
        assert "Design" in (tmp_path / "knowledge-map.svg").read_text()
    assert all(content for content, _ in before.values())
    assert write_plots(model, (), tmp_path) == paths
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == before
