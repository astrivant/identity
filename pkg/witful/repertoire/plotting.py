"""
Render observed toolbox frequency and the hierarchy of problems actually addressed.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from witful.knowledge.plotting import save_figure
from witful.repertoire.journal import counts
from witful.repertoire.layout import problem_figure

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from witful.repertoire.models import Inventory, Use


def write_plots(inventory: Inventory, events: Sequence[Use], destination: Path, *, projection: bool = False) -> tuple[Path, ...]:
    """
    Export plots from validated observations, with question subtitles and no inferred proficiency.

    Args:
        inventory (Inventory): Validated definitions.
        events (Sequence[Use]): Validated task observations.
        destination (Path): Artifact directory owned by the collection.
        projection (bool): Omit outer titles in document exports.

    Returns:
        tuple[Path, ...]: SVG and PNG paths for tool frequency and problem hierarchy.
    """
    tool_counts, problem_counts = counts(inventory, events)
    digest = hashlib.sha256(json.dumps([tool_counts, problem_counts], sort_keys=True).encode()).hexdigest()
    paths = []

    with mpl.rc_context(mpl.rcParamsDefault):
        mpl.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": digest})
        ordered = sorted(inventory.tools, key=lambda item: (-tool_counts[item.id], item.name.casefold()))
        figure = Figure(figsize=(12, max(5, 2.5 + len(ordered) * 0.4)), layout="constrained")
        figure.suptitle("Toolbox use\nWhich tools have supported the most recorded tasks?", fontsize=16, gid="plot-heading")
        axis = figure.subplots()
        axis.barh([item.name for item in ordered], [tool_counts[item.id] for item in ordered], color="#327B69")
        axis.invert_yaxis()
        axis.xaxis.set_major_locator(MaxNLocator(integer=True))
        axis.set_xlabel("Distinct recorded tasks (latest observation per task)")
        axis.spines[["top", "right"]].set_visible(False)

        if not ordered:
            axis.text(0.5, 0.5, "No tools recorded", transform=axis.transAxes, ha="center", va="center")
            axis.set_axis_off()
        figures = [("toolbox-use", figure)]

        figures.append(("problem-repertoire", problem_figure(inventory, problem_counts)))

        for name, figure in figures:
            paths.extend(save_figure(figure, destination, name, projection=projection))

    return tuple(paths)
