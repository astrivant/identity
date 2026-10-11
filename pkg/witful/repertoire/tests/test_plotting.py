"""
Check rendered label containment and node spacing independently of the layout formula.
"""

from __future__ import annotations

from itertools import combinations
from math import hypot
from typing import TYPE_CHECKING

import matplotlib as mpl
import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import PathCollection
from witful.repertoire.layout import problem_figure
from witful.repertoire.models import Inventory, Problem
from witful.repertoire.plotting import write_plots

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("dpi", [72, 130, 200])
def test_labels_fit_circles_without_node_overlap(dpi: int) -> None:
    """
    Measure actual rendered glyphs for varied labels, counts, and hierarchy breadth.

    Args:
        dpi (int): Output resolution used for checking physical label and node geometry.

    Returns:
        None: Text corners remain inside their circles and all circles stay disjoint and within the axes.
    """
    problems = (
        Problem("root", "Operating and improving distributed engineering systems"),
        Problem("short", "QA", "root"),
        Problem("long", "Investigating permission boundaries across asynchronous service integrations", "root"),
        Problem("token", "AnExceptionallyLongUnbrokenCategoryIdentifierThatMustWrap", "root"),
        Problem("leaf", "Deployment recovery", "long"),
    )

    with mpl.rc_context({"font.family": "DejaVu Sans"}):
        figure = problem_figure(Inventory(problems=problems), {p.id: 123456 for p in problems})
        figure.set_dpi(dpi)
        FigureCanvasAgg(figure)
        figure.draw_without_rendering()
        axis = figure.axes[0]
        collection = axis.collections[0]
        assert isinstance(collection, PathCollection)
        positions = np.asarray(collection.get_offsets(), dtype=float)
        centers = np.asarray(collection.get_offset_transform().transform(positions), dtype=float)
        sizes = collection.get_sizes()
        radii = [float(size) ** 0.5 * dpi / 144 for size in sizes]
        texts = {text.get_position(): text for text in axis.texts}

        # Verify the artist output, not a duplicate implementation of the radius calculation.
        for position, center, radius in zip(positions, centers, radii, strict=True):
            bounds = texts[(float(position[0]), float(position[1]))].get_window_extent()

            for x in (bounds.x0, bounds.x1):
                for y in (bounds.y0, bounds.y1):
                    assert hypot(x - center[0], y - center[1]) < radius

            assert center[0] - radius >= axis.bbox.x0 - 1
            assert center[0] + radius <= axis.bbox.x1 + 1
            assert center[1] - radius >= axis.bbox.y0 - 1
            assert center[1] + radius <= axis.bbox.y1 + 1

        for (first, r1), (second, r2) in combinations(zip(centers, radii, strict=True), 2):
            assert hypot(*(first - second)) > r1 + r2

        figure.clear()


def test_empty_taxonomy_and_deterministic_exports(tmp_path: Path) -> None:
    """
    Retain the empty base case, stable output bytes, and title-free document projection.

    Args:
        tmp_path (Path): Isolated output directory for synthetic figures.

    Returns:
        None: Empty figures render, repeated sources retain bytes, and projection removes only the outer heading.
    """
    empty = problem_figure(Inventory(), {})
    FigureCanvasAgg(empty)
    empty.draw_without_rendering()
    assert empty.axes[0].texts[0].get_text() == "No problem categories recorded"
    empty.clear()
    inventory = Inventory(problems=(Problem("one", "Deployment verification and incident recovery"),))
    paths = write_plots(inventory, [], tmp_path)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    write_plots(inventory, [], tmp_path)
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    write_plots(inventory, [], tmp_path, projection=True)
    svg = (tmp_path / "problem-repertoire.svg").read_text()
    assert "How do concrete tasks" not in svg
    assert "Deployment" in svg
