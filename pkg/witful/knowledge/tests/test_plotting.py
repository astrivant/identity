"""
Exercise deterministic rendering at the empty and populated collection boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from matplotlib.collections import PathCollection
from witful.knowledge.models import Discipline, Identity, Skill
from witful.knowledge.plotting import _map_plot, write_plots

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
        rendered = (tmp_path / "knowledge-map.svg").read_text()
        assert "Design" in rendered
        assert "Contracts" in rendered
    assert all(content for content, _ in before.values())
    assert write_plots(model, (), tmp_path) == paths
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == before


def test_map_renders_gaussian_field_and_mean_marker() -> None:
    """
    Keep the Gaussian context and midpoint visible behind and above the bubbles.

    Returns:
        None: The map has one full-viewport image and the two-layer plus marker.
    """
    model = Identity("root", "Example", (Discipline("d", "Design", (Skill("s", "Contracts"),)),))
    figure = _map_plot(model, ())
    axis = figure.axes[0]

    assert len(axis.images) == 1
    marker_sizes = {size for collection in axis.collections if isinstance(collection, PathCollection) for size in collection.get_sizes()}
    assert any(size == pytest.approx(720 * (2 / 3) ** 2) for size in marker_sizes)
    assert any(size == pytest.approx(980 * (2 / 3) ** 2) for size in marker_sizes)
    figure.clear()
