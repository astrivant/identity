"""
Project current decisions into a public figure without exporting their journal or rationale.
"""

from __future__ import annotations

from collections import Counter
from textwrap import fill
from typing import TYPE_CHECKING

import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from witful.knowledge.compiler import index
from witful.knowledge.plotting import save_figure
from witful.life.contracts import current_decisions, snapshot_identity

if TYPE_CHECKING:
    from pathlib import Path

    from matplotlib.axes import Axes

    from witful.life.models import Archive

__all__ = ["draw_influences", "write_influences"]


def draw_influences(axis: Axes, archive: Archive) -> None:
    """
    Count each directly referenced concept once per currently accepted decision.

    Args:
        axis (Axes): Owned by the caller and populated in place.
        archive (Archive): Decision history with its content-addressed source snapshots.

    Returns:
        None: Draws at most fifteen ranked concepts, or an explicit empty state.

    Raises:
        ValueError: The archive is invalid or a referenced snapshot was altered.
    """
    heads = current_decisions(archive)
    snapshots = {snapshot.id: snapshot for snapshot in archive.snapshots}
    counts: Counter[str] = Counter()
    labels: dict[str, str] = {}

    # Revisions replace prior counts; retired decisions contribute no current evidence.
    for event in heads:
        if event.decision.status != "accepted":
            continue

        concepts = index(snapshot_identity(snapshots[event.snapshot_id]))[0]
        counts.update(event.decision.concept_ids)
        labels.update({key: concepts[key].name for key in event.decision.concept_ids})

    selected = sorted(counts, key=lambda key: (-counts[key], key))[:15]
    axis.barh([fill(labels[key], 28) for key in selected], [counts[key] for key in selected], color="#366A87")
    axis.invert_yaxis()
    axis.set_xlabel("Decisions")
    axis.xaxis.set_major_locator(MaxNLocator(integer=True))
    axis.spines[["top", "right"]].set_visible(False)

    if not selected:
        axis.text(0.5, 0.5, "No accepted decisions recorded", ha="center", transform=axis.transAxes)


def write_influences(archive: Archive, output: Path) -> list[Path]:
    """
    Render the decision-influences figure with stable bytes and searchable labels for review.

    Args:
        archive (Archive): Current decision history and source snapshots.
        output (Path): Directory for the derived SVG and PNG only.

    Returns:
        list[Path]: Written figure paths, preserving unchanged files.

    Raises:
        ValueError: Invalid historical evidence prevents rendering.
    """
    # Fix plotting defaults so machine settings do not alter exported labels or image hashes.
    with mpl.rc_context(mpl.rcParamsDefault):
        mpl.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": "decision-influences-v1"})
        figure = Figure(figsize=(12, 9), facecolor="white")
        axis = figure.add_axes((0.35, 0.14, 0.59, 0.69))
        draw_influences(axis, archive)
        figure.text(0.04, 0.95, "What informs my decisions", fontsize=23, color="#263748", weight="bold")
        figure.text(0.04, 0.90, "Which skills and lessons inform my current decisions?", fontsize=11, color="#697783")
        figure.text(0.04, 0.04, "Recorded decisions, not a measure of proficiency.", fontsize=10, color="#697783")
        output.mkdir(parents=True, exist_ok=True)
        return save_figure(figure, output, "decision-influences")
