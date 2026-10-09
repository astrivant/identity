"""
Render reproducible hierarchy, usage, and weighted reuse views for the collection README.
"""

from __future__ import annotations

import hashlib
import json
import math
from io import BytesIO
from textwrap import fill
from typing import TYPE_CHECKING

import matplotlib as mpl
import networkx as nx
from matplotlib.figure import Figure
from matplotlib.patches import Circle

from witful.files import replace_file
from witful.knowledge.applications import effective_applications
from witful.knowledge.compiler import index
from witful.knowledge.contracts import as_data
from witful.knowledge.metrics import graph_edges, usage
from witful.knowledge.models import Discipline, Identity, Lemma, Lesson, Skill

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from witful.knowledge.models import Application

__all__ = ["save_figure", "write_plots"]

_COLORS = ("#366A87", "#407D61", "#A36636", "#795A91", "#996277", "#597878", "#767047", "#66758A")
_INK = "#263748"
_MUTED = "#697783"
_LAYERS = (Identity, Discipline, Skill, Lesson, Lemma)


def save_figure(figure: Figure, destination: Path, name: str) -> list[Path]:
    """
    Preserve unchanged SVG and PNG bytes and modification times.

    Args:
        figure (Figure): Completed headless plot.
        destination (Path): Artifact directory.
        name (str): Stable filename stem.

    Returns:
        list[Path]: Generated or unchanged image paths.
    """
    paths: list[Path] = []

    for extension in ("svg", "png"):
        buffer = BytesIO()
        metadata = {"Date": None, "Creator": "identity knowledge"} if extension == "svg" else {"Software": "identity knowledge"}
        figure.savefig(buffer, format=extension, dpi=130, metadata=metadata)
        content = buffer.getvalue()

        if extension == "svg":
            content = b"\n".join(line.rstrip() for line in content.splitlines()) + b"\n"

        path = destination / f"{name}.{extension}"
        replace_file(path, content, expected=path.read_bytes() if path.exists() else None)
        paths.append(path)

    figure.clear()
    return paths


def _usage_plot(identity: Identity, applications: Sequence[Application]) -> Figure:
    """
    Compare direct applications by abstraction layer with rolled-up skill usage.

    Args:
        identity (Identity): Compiled hierarchy.
        applications (Sequence[Application]): Explicit observations; absence means unknown history.

    Returns:
        Figure: Two panels with integer counts and an explicit recording boundary.
    """
    nodes, _ = index(identity)
    counts = usage(identity, applications)
    events = effective_applications(applications)
    skills = sorted(
        (node for node in nodes.values() if isinstance(node, Skill)), key=lambda node: (-counts[node.id].applications, node.name)
    )
    figure = Figure(figsize=(15, max(6, len(skills) * 0.32 + 2)), facecolor="white")
    left, right = figure.subplots(1, 2, gridspec_kw={"width_ratios": [1, 1.6]})
    figure.subplots_adjust(left=0.14, right=0.95, top=0.85, bottom=0.14, wspace=0.95)
    figure.suptitle("Which building blocks are being used?", fontsize=21, color=_INK, x=0.04, ha="left")
    direct = [sum(any(isinstance(nodes[identifier], kind) for identifier in event.concept_ids) for event in events) for kind in _LAYERS]
    left.barh([kind.__name__ for kind in _LAYERS], direct, color=_COLORS[:5])
    left.invert_yaxis()
    left.set_title("Explicitly recorded level", fontsize=12, color=_INK)
    right.barh(
        [fill(node.name, 27) for node in skills], [counts[node.id].applications for node in skills], color="#CDD7DE", label="All recorded"
    )
    right.barh(
        [fill(node.name, 27) for node in skills], [counts[node.id].verified for node in skills], color="#407D61", label="Reported verified"
    )
    right.invert_yaxis()
    right.set_title("Skills, including applied lessons and lemmas", fontsize=12, color=_INK)
    right.legend(frameon=False, fontsize=9, loc="lower right")

    for axis in (left, right):
        axis.set_xlabel("Distinct task/context observations", fontsize=10, color=_MUTED)
        axis.spines[["top", "right", "left", "bottom"]].set_visible(False)
        axis.tick_params(length=0, labelsize=9)
        axis.set_xlim(0, max(1, max(direct, default=0), max((counts[s.id].applications for s in skills), default=0)) + 0.5)
        axis.xaxis.get_major_locator().set_params(integer=True)
        axis.set_axisbelow(True)
        axis.grid(axis="x", color="#EDF0F2")

    if not events:
        figure.text(0.04, 0.9, "Application history has not been recorded yet.", color=_MUTED, fontsize=12)

    figure.text(
        0.04,
        0.04,
        "Counts describe documented applications, not competence or unobserved reasoning. Revisions count once.",
        fontsize=10,
        color=_MUTED,
    )
    return figure


def _map_plot(identity: Identity, applications: Sequence[Application]) -> Figure:
    """
    Group skills by discipline while weighted reuse links adjust their positions and widths.

    Args:
        identity (Identity): Complete hierarchy and curated relationships.
        applications (Sequence[Application]): Explicit evidence for observed reuse strength.

    Returns:
        Figure: Skill-level overview with separate proposed and observed links.
    """
    counts = usage(identity, applications)
    nodes, _ = index(identity)
    selected = {key: node for key, node in nodes.items() if isinstance(node, (Discipline, Skill))}
    graph: nx.Graph[str, dict[str, object], dict[str, float]] = nx.Graph()
    graph.add_nodes_from(sorted(selected))
    edges = [edge for edge in graph_edges(identity, applications) if edge.source in selected and edge.target in selected]

    for edge in edges:
        weight = 2.0 if edge.kind == "contains" else 0.2 + edge.strength * 2
        existing = graph.get_edge_data(edge.source, edge.target, default={}).get("weight", 0.0)
        graph.add_edge(edge.source, edge.target, weight=max(weight, existing))

    # Fix discipline anchors, seed every child deterministically, and bound relaxation within each organizational cluster.
    anchors: dict[str, tuple[float, float]] = {}
    positions: dict[str, tuple[float, float]] = {}
    owners: dict[str, str] = {}
    discipline_count = max(1, len(identity.disciplines))

    for ordinal, discipline in enumerate(identity.disciplines):
        angle = math.pi / 2 - 2 * math.pi * ordinal / discipline_count
        center = (2.6 * math.cos(angle), 2.6 * math.sin(angle))
        anchors[discipline.id] = center
        positions[discipline.id] = center

        for number, skill in enumerate(discipline.skills):
            theta = 2 * math.pi * number / max(1, len(discipline.skills))
            positions[skill.id] = (center[0] + 0.68 * math.cos(theta), center[1] + 0.68 * math.sin(theta))
            owners[skill.id] = discipline.id

    if graph and anchors:
        relaxed = nx.spring_layout(graph, pos=positions, fixed=sorted(anchors), seed=17, iterations=80, k=0.55, method="force")

        for identifier, owner in owners.items():
            start, center = positions[identifier], anchors[owner]
            point = (0.75 * start[0] + 0.25 * float(relaxed[identifier][0]), 0.75 * start[1] + 0.25 * float(relaxed[identifier][1]))

            # Limit movement from each readable seed slot so a strong bridge cannot collapse neighboring labels.
            displacement = math.dist(point, start)
            adjustment = min(1.0, 0.15 / max(displacement, 0.001))
            point = (start[0] + (point[0] - start[0]) * adjustment, start[1] + (point[1] - start[1]) * adjustment)
            distance = math.dist(point, center)
            ratio = min(1.0, 0.83 / max(distance, 0.001))
            positions[identifier] = (center[0] + (point[0] - center[0]) * ratio, center[1] + (point[1] - center[1]) * ratio)

    figure = Figure(figsize=(14, 13), facecolor="white")
    axis = figure.add_axes((0.03, 0.09, 0.94, 0.8))
    axis.set_aspect("equal")
    axis.set_xlim(-4.1, 4.1)
    axis.set_ylim(-3.9, 3.9)
    axis.axis("off")
    figure.text(0.04, 0.96, "How my skills connect", fontsize=23, color=_INK, weight="bold")
    figure.text(0.04, 0.925, "Where do my skills connect across areas of work?", fontsize=11, color=_MUTED)

    for edge in edges:
        a, b = positions[edge.source], positions[edge.target]
        observed = edge.kind in {"co-use", "observed-transfer"}
        color = "#407D61" if observed and edge.verified else "#BAC4CD"
        axis.plot(
            [a[0], b[0]],
            [a[1], b[1]],
            color=color,
            linewidth=0.6 + 3 * edge.strength,
            linestyle="-" if observed or edge.kind == "contains" else "--",
            alpha=0.65,
            zorder=1,
        )

    for number, discipline in enumerate(identity.disciplines):
        center = anchors[discipline.id]
        color = _COLORS[number % len(_COLORS)]
        axis.add_patch(Circle(center, 1.05, facecolor=color, alpha=0.055, edgecolor="none", zorder=0))
        axis.scatter(*center, s=130, marker="s", color=color, zorder=3)
        axis.text(center[0], center[1] + 1.04, fill(discipline.name, 25), ha="center", va="bottom", color=color, fontsize=11, weight="bold")

        for skill in discipline.skills:
            x, y = positions[skill.id]
            axis.scatter(x, y, s=55 + 45 * math.log1p(counts[skill.id].applications), color=color, zorder=3)
            axis.text(
                x,
                y - 0.09,
                fill(skill.name, 18),
                ha="center",
                va="top",
                color=_INK,
                fontsize=8,
                bbox={"facecolor": "white", "alpha": 0.82, "edgecolor": "none", "pad": 1},
                zorder=4,
            )

    if not selected:
        axis.text(0, 0, "No disciplines recorded", ha="center", color=_MUTED)

    figure.text(
        0.04,
        0.048,
        "Squares: disciplines   Circles: skills   Dashed: curated bridges   Green: reported verified reuse",
        fontsize=10,
        color=_MUTED,
    )
    figure.text(
        0.04,
        0.026,
        "Edge strength is normalized co-use or transfer share, not a probability of correctness. Layout uses fixed seeds and anchors.",
        fontsize=9,
        color=_MUTED,
    )
    return figure


def _hierarchy_plot(identity: Identity) -> Figure:
    """
    Display every discipline's nested skill, lesson, and lemma subgraph.

    Args:
        identity (Identity): Complete compiled hierarchy.

    Returns:
        Figure: One panel per discipline, with compact nodes instead of unreadable full lesson text.
    """
    panels = max(1, len(identity.disciplines))
    height = max(6, math.ceil(panels / 2) * 3.5 + 1.5)
    figure = Figure(figsize=(15, height), facecolor="white")
    axes = figure.subplots(math.ceil(panels / 2), min(2, panels), squeeze=False)

    # Reserve physical space for the title, question, panel labels, and footer at every collection size.
    figure.subplots_adjust(left=0.06, right=0.94, top=1 - 1.15 / height, bottom=0.75 / height, wspace=0.18, hspace=0.65)
    figure.suptitle(identity.name, fontsize=24, color=_INK, x=0.04, y=1 - 0.15 / height, ha="left")
    figure.text(0.04, 1 - 0.58 / height, "How are disciplines, skills, and lessons organized?", fontsize=11, color=_MUTED)

    for axis in axes.flat:
        axis.axis("off")

    for ordinal, discipline in enumerate(identity.disciplines):
        axis = axes.flat[ordinal]
        color = _COLORS[ordinal % len(_COLORS)]
        axis.set_title(discipline.name, fontsize=13, color=color, loc="left", pad=20)
        skills = discipline.skills
        total = sum(max(5, len(skill.lessons)) + 2 for skill in skills)
        cursor = 0
        axis.set_xlim(-0.3, 3.3)
        axis.set_ylim(-1, max(1, total))
        center = max(0, total - 1) / 2
        axis.scatter(0, center, marker="s", color=color, s=85)

        for skill in skills:
            width = max(5, len(skill.lessons))
            position = cursor + (width - 1) / 2
            axis.plot([0, 1], [center, position], color="#CBD3D9", lw=0.7)
            axis.scatter(1, position, color=color, s=55)
            axis.text(0.92, position, fill(skill.name, 21), ha="right", va="center", fontsize=8, color=_INK)

            for number, lesson in enumerate(skill.lessons):
                row = position + number - (len(skill.lessons) - 1) / 2
                axis.plot([1, 2], [position, row], color="#CBD3D9", lw=0.6)
                axis.scatter(2, row, marker="o", color=color, s=18)

                for part, _ in enumerate(lesson.lemmas):
                    point = row + (part - (len(lesson.lemmas) - 1) / 2) * 0.3
                    axis.plot([2, 3], [row, point], color="#CBD3D9", lw=0.6)
                    axis.scatter(3, point, marker="D", color=color, s=13)

            cursor += width + 2

        for column, label in enumerate(("Discipline", "Skill", "Lesson", "Lemma")):
            axis.text(column, -0.1, label, transform=axis.get_xaxis_transform(), fontsize=8, ha="center", color=_MUTED)

    figure.text(
        0.04,
        0.18 / height,
        "Each lesson has one canonical home. Reuse edges live in the connection map; "
        "inspect a concept ID for its full teaching and evidence.",
        fontsize=10,
        color=_MUTED,
    )
    return figure


def write_plots(identity: Identity, applications: Sequence[Application], destination: Path) -> list[Path]:
    """
    Generate the README's three complementary views with explicit, repeatable inputs.

    Args:
        identity (Identity): Validated model.
        applications (Sequence[Application]): Validated application history.
        destination (Path): Directory receiving SVG and PNG versions of each view.

    Returns:
        list[Path]: All six deterministic artifacts for this toolchain and input ordering.
    """
    digest = hashlib.sha256(
        json.dumps([as_data(identity), [as_data(event) for event in applications]], sort_keys=True).encode()
    ).hexdigest()

    with mpl.rc_context(mpl.rcParamsDefault):
        mpl.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": digest})
        return [
            *save_figure(_usage_plot(identity, applications), destination, "knowledge-usage"),
            *save_figure(_map_plot(identity, applications), destination, "knowledge-map"),
            *save_figure(_hierarchy_plot(identity), destination, "knowledge-hierarchy"),
        ]
