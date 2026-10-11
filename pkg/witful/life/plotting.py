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
from witful.life.contracts import current_decisions, snapshot_identity, validate_archive

if TYPE_CHECKING:
    from pathlib import Path

    from matplotlib.axes import Axes

    from witful.life.models import Archive

__all__ = ["draw_changes", "draw_influences", "write_influences"]


def draw_changes(axis: Axes, archive: Archive) -> None:
    """
    Show net accepted-choice changes per observation against a horizontal recording baseline.

    Args:
        axis (Axes): Owned by the caller and populated in place.
        archive (Archive): Decision history in validated causal journal order.

    Returns:
        None: Draws discrete changes and raw totals, or an explicit empty state.

    Raises:
        ValueError: Invalid history prevents interpreting a revision as a state transition.
    """
    validate_archive(archive)
    active: dict[str, bool] = {}
    changes: list[int] = []

    # First differences remove automatic journal growth without treating revisions as new choices.
    for event in archive.events:
        decision = event.decision
        accepted = decision.status == "accepted"
        changes.append(int(accepted) - int(active.get(decision.key, False)))
        active[decision.key] = accepted

    positions = list(range(1, len(changes) + 1))
    axis.set_xlabel("Journal entry")
    axis.set_ylabel("Net change per entry")
    axis.set_yticks([-1, 0, 1], labels=["-1", "0", "+1"])
    axis.set_ylim(-1.35, 1.85)
    axis.xaxis.set_major_locator(MaxNLocator(integer=True))
    axis.axhline(0, color="#D8DDE1", linewidth=0.8, zorder=0)
    axis.text(
        0,
        -0.22,
        f"{len(changes)} observations | {sum(active.values())} accepted choices",
        transform=axis.transAxes,
        fontsize=10,
        color="#697783",
    )

    if not positions:
        axis.set_xticks([])
        axis.text(0.5, 0.5, "No choices recorded", ha="center", va="center", transform=axis.transAxes)
        return

    # A thin dashed baseline over a wider choice line leaves both series visible when they coincide.
    accepted_line = axis.step(
        positions,
        changes,
        where="mid",
        color="#407D61",
        linewidth=3,
        marker="o",
        markersize=4,
        markevery=max(1, len(positions) // 20),
        label="Accepted choices",
        zorder=2,
    )[0]
    observation_line = axis.plot(
        positions,
        [1] * len(positions),
        color="#A36636",
        linewidth=1.5,
        linestyle="--",
        marker="_",
        markersize=8,
        markevery=[0, len(positions) - 1],
        label="Observations (+1 per entry)",
        zorder=3,
    )[0]
    axis.set_xlim(0.5, len(positions) + 0.5)
    axis.legend(handles=[observation_line, accepted_line], frameon=False, loc="upper left", fontsize=9)


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


def write_influences(archive: Archive, output: Path, *, projection: bool = False) -> list[Path]:
    """
    Render the decision-influences figure with stable bytes and searchable labels for review.

    Args:
        archive (Archive): Current decision history and source snapshots.
        output (Path): Directory for the derived SVG and PNG only.
        projection (bool): Omit outer title and question in document projections.

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
        figure.text(0.04, 0.95, "What informs my decisions", fontsize=23, color="#263748", weight="bold", gid="plot-heading")
        figure.text(0.04, 0.90, "Which skills and lessons inform my current decisions?", fontsize=11, color="#697783", gid="plot-heading")
        figure.text(0.04, 0.04, "Recorded decisions, not a measure of proficiency.", fontsize=10, color="#697783")
        output.mkdir(parents=True, exist_ok=True)
        return save_figure(figure, output, "decision-influences", projection=projection)
