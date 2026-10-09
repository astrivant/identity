"""
Render observed toolbox frequency and the hierarchy of problems actually addressed.
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from textwrap import fill
from typing import TYPE_CHECKING

import matplotlib as mpl
import networkx as nx
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from sapience.files import replace_file
from sapience.repertoire.journal import counts

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sapience.repertoire.models import Inventory, Use


def write_plots(inventory: Inventory, events: Sequence[Use], destination: Path) -> tuple[Path, ...]:
    """
    Export plots from validated observations, with question subtitles and no inferred proficiency.

    Args:
        inventory (Inventory): Validated definitions.
        events (Sequence[Use]): Validated task observations.
        destination (Path): Artifact directory owned by the collection.

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
        figure.suptitle("Toolbox use\nWhich tools have supported the most recorded tasks?", fontsize=16)
        axis = figure.subplots()
        axis.barh([item.name for item in ordered], [tool_counts[item.id] for item in ordered], color="#327B69")
        axis.invert_yaxis()
        axis.xaxis.set_major_locator(MaxNLocator(integer=True))
        axis.set_xlabel("Distinct recorded tasks (latest observation per task)")
        axis.spines[["top", "right"]].set_visible(False)
        figures = [("toolbox-use", figure)]

        graph: nx.DiGraph[str, dict[str, object], dict[str, object]] = nx.DiGraph()
        graph.add_nodes_from(item.id for item in inventory.problems)
        graph.add_edges_from((item.parent, item.id) for item in inventory.problems if item.parent is not None)
        labels = {item.id: fill(item.name, 22) + f"\n{problem_counts[item.id]} tasks" for item in inventory.problems}
        positions = {}

        for depth, layer in enumerate(nx.topological_generations(graph)):
            for row, identifier in enumerate(sorted(layer)):
                positions[identifier] = (float(depth), float(-row))

        figure = Figure(figsize=(14, max(5, 2 + len(inventory.problems) * 0.35)), layout="constrained")
        figure.suptitle("Problem repertoire\nHow do concrete tasks connect to broader problem categories?", fontsize=16)
        axis = figure.subplots()

        if graph:
            nx.draw_networkx_edges(graph, positions, ax=axis, arrows=True, node_size=2800, edge_color="#B0BBC2")
            nx.draw_networkx_nodes(graph, positions, ax=axis, node_size=2800, node_color="#E2EFEA", edgecolors="#327B69")
            nx.draw_networkx_labels(graph, positions, labels, ax=axis, font_size=9)
        else:
            axis.text(0.5, 0.5, "No problem categories recorded", ha="center", va="center")

        axis.margins(0.2)
        axis.set_axis_off()
        figures.append(("problem-repertoire", figure))

        for name, figure in figures:
            for extension in ("svg", "png"):
                stream = BytesIO()
                figure.savefig(stream, format=extension, dpi=130, metadata={"Date": None} if extension == "svg" else {})
                path = destination / f"{name}.{extension}"
                replace_file(path, stream.getvalue(), expected=path.read_bytes() if path.exists() else None)
                paths.append(path)

    return tuple(paths)
