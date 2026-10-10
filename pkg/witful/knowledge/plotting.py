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
from matplotlib.figure import Figure
from matplotlib.patches import Circle

from witful.files import replace_file
from witful.knowledge.applications import effective_applications
from witful.knowledge.compiler import index
from witful.knowledge.contracts import as_data
from witful.knowledge.emphasis import emphasis_layout
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


def save_figure(figure: Figure, destination: Path, name: str, *, projection: bool = False) -> list[Path]:
    """
    Preserve unchanged SVG and PNG bytes and modification times.

    Args:
        figure (Figure): Completed headless plot.
        destination (Path): Artifact directory.
        name (str): Stable filename stem.
        projection (bool): Remove marked outer titles and crop unused space for a containing document.

    Returns:
        list[Path]: Generated or unchanged image paths.
    """
    if projection:
        for artist in figure.texts:
            if artist.get_gid() == "plot-heading":
                artist.set_visible(False)
                artist.set_in_layout(False)

    paths: list[Path] = []

    for extension in ("svg", "png"):
        buffer = BytesIO()
        metadata = {"Date": None, "Creator": "identity knowledge"} if extension == "svg" else {"Software": "identity knowledge"}
        figure.savefig(buffer, format=extension, dpi=130, metadata=metadata, bbox_inches="tight" if projection else None)
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
    figure.suptitle("Which building blocks are being used?", fontsize=21, color=_INK, x=0.04, ha="left", gid="plot-heading")
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
    Draw bounded discipline bubbles containing skills while retaining evidence-typed reuse links.

    Args:
        identity (Identity): Complete hierarchy and curated relationships.
        applications (Sequence[Application]): Explicit applications used to rank current working emphasis.

    Returns:
        Figure: Nonoverlapping bubbles with peripheral fading and a separate complete hierarchy export.
    """
    bubbles = emphasis_layout(identity, applications)
    disciplines = {discipline.id: discipline for discipline in identity.disciplines}
    colors = {discipline.id: _COLORS[index % len(_COLORS)] for index, discipline in enumerate(identity.disciplines)}
    positions: dict[str, tuple[float, float]] = {}
    opacity: dict[str, float] = {}
    figure = Figure(figsize=(12, 12), facecolor="white")
    axis = figure.add_axes((0.035, 0.11, 0.93, 0.78))
    axis.set_aspect("equal")
    axis.set_xlim(-1.05, 1.05)
    axis.set_ylim(-1.05, 1.05)
    axis.axis("off")
    figure.text(0.04, 0.96, "How my skills connect", fontsize=23, color=_INK, weight="bold", gid="plot-heading")
    figure.text(0.04, 0.925, "Which areas of work are in focus, and how do they connect?", fontsize=11, color=_MUTED, gid="plot-heading")

    # Discipline bubbles replace the old square anchors; skill dots remain their nested subgraphs.
    for bubble in bubbles:
        discipline = disciplines[bubble.id]
        positions[bubble.id] = (bubble.x, bubble.y)
        opacity[bubble.id] = bubble.opacity
        skills = sorted(discipline.skills, key=lambda item: item.id)
        axis.add_patch(
            Circle(
                (bubble.x, bubble.y),
                bubble.radius,
                facecolor=colors[bubble.id],
                edgecolor=colors[bubble.id],
                alpha=0.18 * bubble.opacity,
                linewidth=1.2,
                zorder=2,
            )
        )
        axis.text(
            bubble.x,
            bubble.y + bubble.radius * 0.13,
            fill(discipline.name, 16, break_on_hyphens=False),
            ha="center",
            va="center",
            color=colors[bubble.id],
            alpha=bubble.opacity,
            fontsize=8 + 15 * bubble.radius,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.80, "pad": 1.5},
            weight="bold",
            zorder=4,
        )

        for ordinal, skill in enumerate(skills):
            angle = math.pi * (1.15 + 0.70 * (ordinal + 0.5) / max(1, len(skills)))
            point = (bubble.x + bubble.radius * 0.73 * math.cos(angle), bubble.y + bubble.radius * 0.73 * math.sin(angle))
            positions[skill.id] = point
            opacity[skill.id] = bubble.opacity
            axis.scatter(*point, s=13 + 40 * bubble.radius, color=colors[bubble.id], alpha=bubble.opacity, zorder=4)

    # Only the viewport is filtered. Preserve link kinds and full-graph weights instead of recomputing evidence on a subset.
    for edge in graph_edges(identity, applications):
        if edge.source not in positions or edge.target not in positions:
            continue

        a, b = positions[edge.source], positions[edge.target]
        observed = edge.kind in {"co-use", "observed-transfer"}
        axis.plot(
            [a[0], b[0]],
            [a[1], b[1]],
            color="#407D61" if observed and edge.verified else "#BAC4CD",
            linewidth=0.5 + 2.5 * edge.strength,
            linestyle="-" if observed or edge.kind == "contains" else "--",
            alpha=0.55 * min(opacity[edge.source], opacity[edge.target]),
            zorder=1,
        )

    if not bubbles:
        axis.text(0, 0, "No disciplines recorded", ha="center", color=_MUTED)

    elif not any(bubble.score for bubble in bubbles):
        figure.text(0.04, 0.09, "No applications recorded; placement does not imply use.", color=_MUTED, fontsize=10)

    figure.text(
        0.04, 0.065, "Bubbles: areas of work   Dots: skills   Dashed: curated links   Green: verified reuse", fontsize=9, color=_MUTED
    )
    figure.text(
        0.04,
        0.043,
        "Size and position: recent recorded use. Peripheral fading shows emphasis, not lost knowledge.",
        fontsize=9,
        color=_MUTED,
    )
    figure.text(
        0.04,
        0.021,
        f"Showing {len(bubbles)} of {len(identity.disciplines)} areas. Complete hierarchy and history remain available.",
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
    figure.suptitle(identity.name, fontsize=24, color=_INK, x=0.04, y=1 - 0.15 / height, ha="left", gid="plot-heading")
    figure.text(
        0.04, 1 - 0.58 / height, "How are disciplines, skills, and lessons organized?", fontsize=11, color=_MUTED, gid="plot-heading"
    )

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


def write_plots(identity: Identity, applications: Sequence[Application], destination: Path, *, projection: bool = False) -> list[Path]:
    """
    Generate the README's three complementary views with explicit, repeatable inputs.

    Args:
        identity (Identity): Validated model.
        applications (Sequence[Application]): Validated application history.
        destination (Path): Directory receiving SVG and PNG versions of each view.
        projection (bool): Export without outer titles for captions owned by a containing document.

    Returns:
        list[Path]: All six deterministic artifacts for this toolchain and input ordering.
    """
    digest = hashlib.sha256(
        json.dumps([as_data(identity), [as_data(event) for event in applications]], sort_keys=True).encode()
    ).hexdigest()

    with mpl.rc_context(mpl.rcParamsDefault):
        mpl.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": digest})
        return [
            *save_figure(_usage_plot(identity, applications), destination, "knowledge-usage", projection=projection),
            *save_figure(_map_plot(identity, applications), destination, "knowledge-map", projection=projection),
            *save_figure(_hierarchy_plot(identity), destination, "knowledge-hierarchy", projection=projection),
        ]
