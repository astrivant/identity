"""
Lay out problem categories using measured labels and nonoverlapping circular nodes.
"""

from __future__ import annotations

from math import hypot
from textwrap import fill
from typing import TYPE_CHECKING

import networkx as nx
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.text import Text

if TYPE_CHECKING:
    from witful.repertoire.models import Inventory

_FONT_SIZE = 9
_LABEL_PADDING = 9.0
_LAYER_GAP = 54.0
_ROW_GAP = 24.0
_MARGIN = 24.0
_HEADING_SPACE = 62.0
_POINTS_PER_INCH = 72.0


def problem_figure(inventory: Inventory, counts: dict[str, int]) -> Figure:
    """
    Fit circles around their full labels and allocate physical space for each hierarchy layer.

    Args:
        inventory (Inventory): Validated acyclic problem taxonomy.
        counts (dict[str, int]): Observed task counts keyed by every problem identifier.

    Returns:
        Figure: Deterministic plot with a fixed label font and circles large enough for every text corner.
    """
    graph: nx.DiGraph[str, dict[str, object], dict[str, object]] = nx.DiGraph()
    graph.add_nodes_from(sorted(item.id for item in inventory.problems))
    graph.add_edges_from(sorted((item.parent, item.id) for item in inventory.problems if item.parent is not None))
    labels = {
        item.id: fill(item.name, 22) + f"\n{counts[item.id]} {'task' if counts[item.id] == 1 else 'tasks'}" for item in inventory.problems
    }
    figure = Figure(dpi=_POINTS_PER_INCH)
    FigureCanvasAgg(figure)
    radii: dict[str, float] = {}

    # At 72 DPI, measured pixels are points. Enclose the label's diagonal, not only its width.
    for identifier, label in labels.items():
        text = Text(text=label, fontsize=_FONT_SIZE, ha="center", va="center")
        text.set_figure(figure)
        bounds = text.get_window_extent()
        radii[identifier] = hypot(bounds.width, bounds.height) / 2 + _LABEL_PADDING

    layers = [sorted(layer) for layer in nx.topological_generations(graph)]
    widths = [max(2 * radii[node] for node in layer) for layer in layers]
    heights = [sum(2 * radii[node] for node in layer) + _ROW_GAP * (len(layer) - 1) for layer in layers]
    natural_width = sum(widths) + _LAYER_GAP * max(0, len(layers) - 1)
    content_width = max(14 * _POINTS_PER_INCH - 2 * _MARGIN, natural_width)
    content_height = max(5 * _POINTS_PER_INCH - 2 * _MARGIN - _HEADING_SPACE, max(heights, default=0))
    width = content_width + 2 * _MARGIN
    height = content_height + 2 * _MARGIN + _HEADING_SPACE
    figure.set_size_inches(width / _POINTS_PER_INCH, height / _POINTS_PER_INCH)

    # Keep one data unit equal to a physical point so saving at another DPI cannot shrink nodes around fixed-size text.
    axis = figure.add_axes((_MARGIN / width, _MARGIN / height, content_width / width, content_height / height))
    axis.set_xlim(0, content_width)
    axis.set_ylim(0, content_height)
    axis.set_axis_off()
    figure.suptitle(
        "Problem repertoire\nHow do concrete tasks connect to broader problem categories?",
        fontsize=16,
        y=1 - 12 / height,
        gid="plot-heading",
    )
    positions: dict[str, tuple[float, float]] = {}
    left = (content_width - natural_width) / 2

    # Center each layer vertically; cumulative diameters reserve room even when neighboring labels differ greatly.
    for layer, layer_width, layer_height in zip(layers, widths, heights, strict=True):
        top = (content_height + layer_height) / 2

        for identifier in layer:
            radius = radii[identifier]
            positions[identifier] = (left + layer_width / 2, top - radius)
            top -= 2 * radius + _ROW_GAP

        left += layer_width + _LAYER_GAP

    if graph:
        sizes = [(2 * radii[node]) ** 2 for node in graph]
        nx.draw_networkx_edges(graph, positions, ax=axis, arrows=True, node_size=sizes, edge_color="#B0BBC2")
        nx.draw_networkx_nodes(graph, positions, ax=axis, node_size=sizes, node_color="#E2EFEA", edgecolors="#327B69")
        nx.draw_networkx_labels(graph, positions, labels, ax=axis, font_size=_FONT_SIZE)
    else:
        axis.text(0.5, 0.5, "No problem categories recorded", transform=axis.transAxes, ha="center", va="center")

    return figure
