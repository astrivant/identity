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
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Ellipse
from matplotlib.path import Path as PlotPath
from matplotlib.transforms import Bbox

from witful.files import replace_file
from witful.knowledge.applications import effective_applications
from witful.knowledge.compiler import index
from witful.knowledge.contracts import as_data
from witful.knowledge.emphasis import _gaussian_distance, _gaussian_profile, emphasis_layout
from witful.knowledge.map_axes import GaussianAxis, draw_principal_axes, principal_axes
from witful.knowledge.map_labels import label_color, place_labels, visible_segments
from witful.knowledge.metrics import graph_edges, usage
from witful.knowledge.models import Discipline, Identity, Insight, Lesson, Skill

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from witful.knowledge.models import Application

__all__ = ["save_figure", "write_plots"]

_COLORS = ("#366A87", "#407D61", "#A36636", "#795A91", "#996277", "#597878", "#767047", "#66758A")
_INK = "#263748"
_MUTED = "#697783"
_BUBBLE_ALPHA = 0.18
_GRADIENT_ALPHA = 0.34
# Scatter size is area in points squared; scale by (2/3)^2 for two-thirds linear size.
_MEAN_MARKER_SCALE = 2 / 3
_MEAN_MARKER_SIZE = 720 * _MEAN_MARKER_SCALE**2
_MEAN_MARKER_UNDERLAY_SIZE = 980 * _MEAN_MARKER_SCALE**2
_GAUSSIAN_CONTOURS = (0.5, 1.0, 1.5, 2.0)
_LAYERS = (Identity, Discipline, Skill, Lesson, Insight)


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
    right.set_title("Skills, including applied lessons and insights", fontsize=12, color=_INK)
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
    guides: tuple[GaussianAxis, ...] = ()

    if bubbles:
        profile = _gaussian_profile([(bubble.x, bubble.y) for bubble in bubbles], [bubble.score for bubble in bubbles])

        # One center has no directional spread; its regularization alone must not imply measured axes.
        if len(bubbles) > 1:
            guides = principal_axes(profile)

    # Expand only the view for exterior annotations; packing, covariance, and opacity retain their original coordinates.
    extent = max([1.05, *(abs(value) + 0.2 for guide in guides for point in (guide.label_start, guide.label_end) for value in point)])
    # Preserve the physical room for existing labels while extending the canvas for the statistical guides.
    side = 12 * extent / 1.05
    figure = Figure(figsize=(side, side), facecolor="white")
    axis = figure.add_axes((0.035, 0.11, 0.93, 0.78))
    axis.set_aspect("equal")
    axis.set_xlim(-extent, extent)
    axis.set_ylim(-extent, extent)
    axis.axis("off")
    axis.apply_aspect()
    FigureCanvasAgg(figure)
    figure.draw_without_rendering()
    exclusions: list[Bbox] = []
    obstacles: list[Bbox] = []
    figure.text(0.04, 0.96, "How my skills connect", fontsize=23, color=_INK, weight="bold", gid="plot-heading")
    figure.text(0.04, 0.925, "Which areas of work are in focus, and how do they connect?", fontsize=11, color=_MUTED, gid="plot-heading")

    # Render the same weighted discipline Gaussian as a quiet, continuous shadow behind the bubbles.
    if bubbles:
        coordinates = tuple(-extent + 2 * extent * index / 127 for index in range(128))
        field = [[math.exp(-0.5 * _gaussian_distance((x, y), profile) ** 2) for x in coordinates] for y in coordinates]
        gradient = mpl.colors.LinearSegmentedColormap.from_list("discipline-shadow", ("#F8FAFB", "#8798A6"))
        axis.imshow(
            field,
            extent=(-extent, extent, -extent, extent),
            origin="lower",
            cmap=gradient,
            vmin=0,
            vmax=1,
            alpha=_GRADIENT_ALPHA,
            interpolation="bicubic",
            zorder=-2,
        )

        # Use covariance principal axes, not axis-aligned distances or confidence-probability labels.
        for sigma in _GAUSSIAN_CONTOURS:
            axis.add_patch(
                Ellipse(
                    (profile[0], profile[1]),
                    width=2 * sigma * math.sqrt(profile[2]),
                    height=2 * sigma * math.sqrt(profile[3]),
                    angle=math.degrees(math.atan2(profile[5], profile[4])),
                    facecolor="none",
                    edgecolor="#879198",
                    linewidth=0.8,
                    linestyle="-" if sigma.is_integer() else "--",
                    alpha=0.65,
                    zorder=-1,
                    gid=f"gaussian-contour:{sigma:g}",
                )
            )

        # Reserve the mean marker's display footprint before fitting any label.
        marker_radius = (math.sqrt(_MEAN_MARKER_UNDERLAY_SIZE) / 2 + 3) * figure.dpi / 72
        center_x, center_y = axis.transData.transform((profile[0], profile[1]))
        obstacles.append(
            Bbox.from_extents(
                center_x - marker_radius, center_y - marker_radius, center_x + marker_radius, center_y + marker_radius
            ).transformed(axis.transData.inverted())
        )

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
                alpha=_BUBBLE_ALPHA * bubble.opacity,
                linewidth=1.2,
                zorder=2,
            )
        )
        # Measure labels against the final canvas; light fills require dark, fully opaque type.
        density = math.exp(-0.5 * _gaussian_distance((bubble.x, bubble.y), profile) ** 2)
        shadow = gradient(density)[:3]
        red, green, blue = (_GRADIENT_ALPHA * channel + 1 - _GRADIENT_ALPHA for channel in shadow)
        background = mpl.colors.to_hex((red, green, blue))
        lettering = label_color(colors[bubble.id], _BUBBLE_ALPHA * bubble.opacity, background)
        vertices, bounds = place_labels(axis, bubble, discipline, lettering, obstacles)
        positions.update(vertices)
        exclusions.extend(bounds)

        for skill in skills:
            opacity[skill.id] = bubble.opacity
            axis.scatter(*vertices[skill.id], s=13 + 40 * bubble.radius, color=colors[bubble.id], alpha=bubble.opacity, zorder=4)

    # Opposite winding cuts text-sized holes in contour lines, without a visible label backplate.
    viewport = PlotPath([(-extent, -extent), (extent, -extent), (extent, extent), (-extent, extent), (-extent, -extent)])
    holes = [PlotPath([(b.x0, b.y0), (b.x0, b.y1), (b.x1, b.y1), (b.x1, b.y0), (b.x0, b.y0)]) for b in exclusions]
    clip = PlotPath.make_compound_path(viewport, *holes)

    for patch in axis.patches:
        if (patch.get_gid() or "").startswith("gaussian-contour:"):
            patch.set_clip_path(clip, axis.transData)

    # Only the viewport is filtered. Preserve link kinds and full-graph weights instead of recomputing evidence on a subset.
    for edge in graph_edges(identity, applications):
        if edge.source not in positions or edge.target not in positions:
            continue

        a, b = positions[edge.source], positions[edge.target]
        observed = edge.kind in {"co-use", "observed-transfer"}
        # Leave clear intervals around glyphs instead of hiding links behind opaque label boxes.
        for left, right in visible_segments(a, b, (*exclusions, *obstacles)):
            axis.plot(
                [left[0], right[0]],
                [left[1], right[1]],
                color="#407D61" if observed and edge.verified else "#BAC4CD",
                linewidth=0.5 + 2.5 * edge.strength,
                linestyle="-" if observed or edge.kind == "contains" else "--",
                alpha=0.55 * min(opacity[edge.source], opacity[edge.target]),
                zorder=1,
            )

    draw_principal_axes(axis, guides, (*exclusions, *obstacles))

    if bubbles:
        # Draw the fitted weighted mean last so the midpoint remains visible
        # over bubble fills and relationship lines; titles keep the highest layer.
        axis.scatter(
            profile[0],
            profile[1],
            marker="+",
            color="white",
            s=_MEAN_MARKER_UNDERLAY_SIZE,
            linewidths=5.0 * _MEAN_MARKER_SCALE,
            zorder=9,
        )
        axis.scatter(profile[0], profile[1], marker="+", color=_MUTED, s=_MEAN_MARKER_SIZE, linewidths=2.8 * _MEAN_MARKER_SCALE, zorder=10)

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
        f"Showing {len(bubbles)} of {len(identity.disciplines)} areas. Ellipses: 0.5, 1, 1.5, 2 SD. Complete history remains available.",
        fontsize=9,
        color=_MUTED,
    )
    return figure


def _hierarchy_plot(identity: Identity) -> Figure:
    """
    Display every discipline's nested skill, lesson, and insight subgraph.

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

                for part, _ in enumerate(lesson.insights):
                    point = row + (part - (len(lesson.insights) - 1) / 2) * 0.3
                    axis.plot([2, 3], [row, point], color="#CBD3D9", lw=0.6)
                    axis.scatter(3, point, marker="D", color=color, s=13)

            cursor += width + 2

        for column, label in enumerate(("Discipline", "Skill", "Lesson", "Insight")):
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
