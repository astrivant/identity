"""
Render compact decision revision lanes with explicitly recorded alternative branches.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import shorten, wrap
from typing import TYPE_CHECKING

from matplotlib.figure import Figure
from matplotlib.text import Text

from witful.life.paths import select

if TYPE_CHECKING:
    from witful.life.models import Archive

__all__ = ["figure"]

RESOURCES = Path(__file__).with_name("resources")


def figure(archive: Archive) -> Figure:
    """
    Show eight recent subjects with five explicit revisions each and visible omission accounting.

    Args:
        archive (Archive): Complete journal; disconnected subjects never gain causal edges.

    Returns:
        Figure: Transparent, bounded Garamond plot; complete text remains in the accompanying JSON.
    """
    view = select(archive)
    palette = json.loads((RESOURCES / "palette.json").read_text())
    ink = palette["foreground"]
    slate, sage, red, ochre, *_ = palette["series"]
    height = max(3.2, 2.5 + len(view.lanes) * 0.9)
    result = Figure(figsize=(14, height), facecolor="none")
    result.patch.set_alpha(0)
    axis = result.add_axes((0.02, 1 / height, 0.96, (height - 2) / height))
    axis.set(xlim=(-3.6, 8), ylim=(-0.65, max(0.65, len(view.lanes) - 0.35)))
    axis.invert_yaxis()
    axis.set_axis_off()
    result.text(0.03, 1 - 0.35 / height, "Life: choices and revisions", fontsize=24, color=ink, gid="plot-heading")
    result.text(
        0.03,
        1 - 0.72 / height,
        "Which choices remain, and where did I change direction?",
        fontsize=13,
        color=ink,
        gid="plot-heading",
    )
    numbers = {event.id: ordinal for ordinal, event in enumerate(archive.events, 1)}
    for row, lane in enumerate(view.lanes):
        head = lane.events[-1]
        axis.text(-3.6, row, "\n".join(wrap(shorten(head.decision.title, width=61), 29)), va="center", color=ink, fontsize=12)
        offset = 4 - len(lane.events) + 1
        for step, event in enumerate(lane.events):
            x = offset + step
            current = event.id == head.id
            retired = event.decision.status == "retired"
            color = red if retired else sage if current else slate

            # Adjacent displayed nodes share an explicit supersedes edge. No edge crosses subjects.
            if step:
                axis.annotate("", xy=(x - 0.12, row), xytext=(x - 0.88, row), arrowprops={"arrowstyle": "->", "color": slate, "lw": 1.5})
            axis.plot(
                x,
                row,
                marker="X" if retired else "o",
                markersize=12,
                markerfacecolor=color if current else "none",
                markeredgecolor=color,
                markeredgewidth=1.7,
            )
            axis.text(x, row - 0.20, f"#{numbers[event.id]}", ha="center", fontsize=10, color=ink)
            if event.decision.alternatives:
                axis.plot([x, x + 0.22], [row + 0.10, row + 0.33], linestyle=":", color=ochre, linewidth=1.6)
                axis.text(x + 0.24, row + 0.33, f"{len(event.decision.alternatives)} alt.", va="center", fontsize=10, color=ink)

        if lane.omitted:
            axis.text(offset - 0.4, row, f"+{lane.omitted}", ha="right", va="center", fontsize=10, color=slate)
        status = "Retired" if head.decision.status == "retired" else "Current"
        label = shorten(head.decision.choice, width=83)
        axis.text(4.45, row, "\n".join(wrap(f"{status}: {label}", 42)), va="center", fontsize=12, color=ink)

    if not view.lanes:
        axis.text(0.5, 0.5, "No choices recorded", ha="center", transform=axis.transAxes, color=ink, fontsize=14)
    result.text(
        0.03,
        0.63 / height,
        "Arrows: explicit revisions   Hollow: earlier choice   Filled: current   X: retired   Dotted: recorded alternatives, not outcomes",
        fontsize=11,
        color=ink,
    )
    result.text(
        0.03,
        0.29 / height,
        f"{view.total_events} entries | {len(view.lanes)} subjects shown | {view.omitted_subjects} other subjects, "
        f"{view.omitted_events} entries outside view. Latest subjects first; # is journal order. Full history: life.json",
        fontsize=10,
        color=ink,
    )
    # Resolve exact packaged font bytes instead of depending on an installed system font.
    for text in result.findobj(Text):
        properties = text.get_fontproperties().copy()
        properties.set_file(str(RESOURCES / "EBGaramond-Regular.otf"))
        text.set_fontproperties(properties)
    return result
