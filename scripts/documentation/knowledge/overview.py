"""
Draw a documentation-only ownership forest without merging the example collections.
"""

from __future__ import annotations

from collections import defaultdict
from textwrap import fill
from typing import TYPE_CHECKING

from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from witful.knowledge.compiler import index
from witful.knowledge.models import Discipline, Identity, Insight, Lesson, Skill

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .examples import Example

_KINDS = (Identity, Discipline, Skill, Lesson, Insight)
_FILLS = ("#d6e0e9", "#d6e0e9", "#e2ddba", "#efd6c5", "#f5e6dc")
_INK = "#263642"
_LINE = "#65737b"


def _positions(children: dict[str, list[str]], root: str) -> dict[str, float]:
    """
    Center ancestors between their descendants while preserving every leaf row.

    Args:
        children (dict[str, list[str]]): Owned edges from the validated hierarchy.
        root (str): Identity node from which to traverse.

    Returns:
        dict[str, float]: Stable vertical coordinates, independent of other collections.
    """
    positions: dict[str, float] = {}
    cursor = 0

    def place(identifier: str) -> float:
        """
        Lay out a complete subtree before placing its owner.

        Args:
            identifier (str): Existing node in this hierarchy.

        Returns:
            float: Stable vertical position in leaf rows.
        """
        nonlocal cursor
        descendants = children.get(identifier, [])

        if descendants:
            values = [place(child) for child in descendants]
            row = (min(values) + max(values)) / 2
        else:
            row = float(cursor)
            cursor += 1

        positions[identifier] = row
        return row

    place(root)
    return positions


def overview(examples: Sequence[Example]) -> Figure:
    """
    Show every named hierarchy node in separate identity panels, retaining all five levels.

    Args:
        examples (Sequence[Example]): Nonempty synthetic collections with distinct roots.

    Returns:
        Figure: Ownership-only view; observed and curated links belong in the separate collection maps.

    Raises:
        ValueError: No examples were supplied or a hierarchy has duplicate or incomplete nodes.
    """
    if not examples:
        raise ValueError("The ownership preview requires at least one example")

    indexed = [index(example.identity) for example in examples]
    rows = [sum(isinstance(node, Insight) for node in nodes.values()) for nodes, _ in indexed]
    heights = [max(4.5, count * 0.65 + 1.2) for count in rows]
    height = sum(heights) + 1.4
    figure = Figure(figsize=(17, height), facecolor="#fffdf8")
    figure.text(0.025, 1 - 0.32 / height, "Independent identities, connected knowledge", fontsize=23, weight="bold", color=_INK)
    figure.text(
        0.025,
        1 - 0.7 / height,
        "What does each collection own, from an area of practice to a concrete finding?",
        fontsize=13,
        color=_LINE,
    )
    top = 1.1

    for example, (nodes, parents), count, panel_height in zip(examples, indexed, rows, heights, strict=True):
        axis = figure.add_axes((0.025, 1 - (top + panel_height) / height, 0.95, (panel_height - 0.25) / height))
        axis.set_xlim(-0.5, 4.5)
        axis.set_ylim(-1.7, max(1, count) + 0.9)
        axis.invert_yaxis()
        axis.axis("off")
        children: dict[str, list[str]] = defaultdict(list)

        for child, parent in parents.items():
            children[parent].append(child)

        positions = _positions(children, example.identity.id)
        columns = {identifier: _KINDS.index(type(node)) for identifier, node in nodes.items()}

        for column, kind in enumerate(_KINDS):
            axis.text(column, -1.1, kind.__name__, ha="center", fontsize=12, weight="bold", color=_INK)

        for child, parent in parents.items():
            axis.add_patch(
                FancyArrowPatch(
                    (columns[parent] + 0.41, positions[parent]),
                    (columns[child] - 0.41, positions[child]),
                    arrowstyle="-|>",
                    mutation_scale=9,
                    color=_LINE,
                    linewidth=0.8,
                    zorder=1,
                )
            )

        for identifier, node in nodes.items():
            column, row = columns[identifier], positions[identifier]
            axis.add_patch(
                FancyBboxPatch(
                    (column - 0.4, row - 0.34),
                    0.8,
                    0.68,
                    boxstyle="round,pad=0.02,rounding_size=0.06",
                    facecolor=_FILLS[column],
                    edgecolor=_LINE,
                    linewidth=0.7,
                    zorder=2,
                    gid=f"concept:{identifier}",
                )
            )
            axis.text(column, row, fill(node.name, 20), ha="center", va="center", fontsize=11, color=_INK, zorder=3)

        axis.text(
            -0.43,
            count + 0.12,
            f"{example.identity.name} only: {len(nodes)} concepts, {len(example.applications)} invented task observations.",
            fontsize=10.5,
            color=_LINE,
        )
        top += panel_height

    figure.text(
        0.025,
        0.3 / height,
        "Solid arrows: ownership. Repeated skill names have separate records. All identities and activity are synthetic.",
        fontsize=11,
        color=_LINE,
    )
    return figure
