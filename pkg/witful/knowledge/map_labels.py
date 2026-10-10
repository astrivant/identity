"""
Fit centered map labels inside discipline circles and keep relationship lines clear of text.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from matplotlib.colors import to_rgb

if TYPE_CHECKING:
    from collections.abc import Sequence

    from matplotlib.axes import Axes
    from matplotlib.text import Text
    from matplotlib.transforms import Bbox

    from witful.knowledge.emphasis import Bubble
    from witful.knowledge.models import Discipline

__all__ = ["label_color", "place_labels", "visible_segments"]

_INK = "#263748"
_TITLE_SIZE = 11.0
_SKILL_SIZE = 7.2


def label_color(color: str, opacity: float, background: str) -> str:
    """
    Choose opaque light or dark lettering from the composited bubble's contrast.

    Args:
        color (str): Bubble fill color.
        opacity (float): Effective fill alpha, including peripheral fading.
        background (str): Gaussian backdrop color at the bubble center.

    Returns:
        str: White or dark ink, whichever has the higher luminance contrast.
    """
    channels = [opacity * front + (1 - opacity) * back for front, back in zip(to_rgb(color), to_rgb(background), strict=True)]
    luminance = sum(
        weight * (channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4)
        for weight, channel in zip((0.2126, 0.7152, 0.0722), channels, strict=True)
    )
    dark_luminance = sum(
        weight * ((channel + 0.055) / 1.055) ** 2.4 for weight, channel in zip((0.2126, 0.7152, 0.0722), to_rgb(_INK), strict=True)
    )
    return "white" if 1.05 / (luminance + 0.05) > (luminance + 0.05) / (dark_luminance + 0.05) else _INK


def _wrap(label: Text, name: str, width: float) -> None:
    """
    Wrap on word boundaries using rendered widths instead of character counts.

    Args:
        label (Text): Artist whose font properties determine the measurement.
        name (str): Full concept name; words are never abbreviated or split.
        width (float): Maximum row width in display pixels.

    Returns:
        None: The artist receives its measured multiline text.
    """
    lines: list[str] = []
    current = ""

    for word in name.split():
        candidate = f"{current} {word}".strip()
        label.set_text(candidate)

        if current and label.get_window_extent().width > width:
            lines.append(current)
            current = word
        else:
            current = candidate

    label.set_text("\n".join([*lines, current]))


def place_labels(
    axis: Axes, bubble: Bubble, discipline: Discipline, color: str, obstacles: Sequence[Bbox]
) -> tuple[dict[str, tuple[float, float]], list[Bbox]]:
    """
    Pack measured labels at fixed sizes per hierarchy level without boxes, collisions, or lost names.

    Args:
        axis (Axes): Map axes with final limits and aspect applied.
        bubble (Bubble): Parent circle whose selection and geometry remain unchanged.
        discipline (Discipline): Complete title and skills to display.
        color (str): Opaque, contrast-checked lettering color.
        obstacles (Sequence[Bbox]): Reserved areas in data coordinates, including the mean marker.

    Returns:
        tuple[dict[str, tuple[float, float]], list[Bbox]]: Vertex locations and padded text exclusions in data coordinates.

    Raises:
        ValueError: Complete names cannot fit at their fixed hierarchy sizes.
    """
    skills = sorted(discipline.skills, key=lambda skill: skill.id)
    names = [discipline.name, *(skill.name for skill in skills)]
    identifiers = [discipline.id, *(skill.id for skill in skills)]
    labels = [
        axis.text(
            bubble.x,
            bubble.y,
            "",
            ha="center",
            va="center",
            multialignment="center",
            color=color,
            alpha=1.0,
            weight="bold" if ordinal == 0 else "normal",
            zorder=20 if ordinal == 0 else 12,
            gid=f"map-{'discipline' if ordinal == 0 else 'skill'}:{identifier}",
        )
        for ordinal, identifier in enumerate(identifiers)
    ]
    radius = bubble.radius
    padding = radius * 0.035
    pixels_per_unit = axis.transData.transform((1, 0))[0] - axis.transData.transform((0, 0))[0]
    centers = [
        (bubble.x + radius * column / 12, bubble.y + radius * row / 12)
        for row in range(9, -10, -1)
        for column in sorted(range(-9, 10), key=lambda value: (abs(value), value))
    ]

    # Try wide rows and compact columns without changing type size from one bubble to another.
    for width_ratio in (1.55, 0.86):
        boxes: list[Bbox] = []
        placed: dict[str, tuple[float, float]] = {}

        for ordinal, (label, name, identifier) in enumerate(zip(labels, names, identifiers, strict=True)):
            label.set_fontsize(_TITLE_SIZE if ordinal == 0 else _SKILL_SIZE)
            _wrap(label, name, radius * (1.55 if ordinal == 0 else width_ratio) * pixels_per_unit)

            # Titles occupy the upper cap; skill labels use the remaining measured space.
            candidates = [(bubble.x, y) for x, y in centers if x == bubble.x and y >= bubble.y] if ordinal == 0 else centers

            for center in candidates:
                label.set_position(center)
                bounds = label.get_window_extent().transformed(axis.transData.inverted()).padded(padding)
                corners = ((x, y) for x in (bounds.x0, bounds.x1) for y in (bounds.y0, bounds.y1))

                if any(math.dist(point, (bubble.x, bubble.y)) > radius * 0.96 for point in corners):
                    continue

                if ordinal and bounds.y1 > boxes[0].y0:
                    continue

                if any(bounds.overlaps(other) for other in (*boxes, *obstacles)):
                    continue

                boxes.append(bounds)
                placed[identifier] = (center[0], bounds.y0 + padding / 2) if ordinal else (bubble.x, bubble.y)
                break
            else:
                break
        else:
            return placed, boxes

    # Dense or exceptionally long input must not silently erase labels or render an unreadable collision.
    for label in labels:
        label.remove()

    raise ValueError(f"Map labels do not fit discipline {discipline.id}; use a smaller map selection or shorter display names")


def visible_segments(
    start: tuple[float, float], end: tuple[float, float], exclusions: Sequence[Bbox]
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """
    Clip relationship segments around text rectangles without painting label backgrounds.

    Args:
        start (tuple[float, float]): Source vertex in data coordinates.
        end (tuple[float, float]): Target vertex in data coordinates.
        exclusions (Sequence[Bbox]): Padded text bounds to leave clear.

    Returns:
        list[tuple[tuple[float, float], tuple[float, float]]]: Visible intervals preserving the original straight edge.
    """
    hidden: list[tuple[float, float]] = []

    for box in exclusions:
        low, high = 0.0, 1.0

        # Intersect the line's parameter interval with each rectangle's two slabs.
        for origin, finish, minimum, maximum in ((start[0], end[0], box.x0, box.x1), (start[1], end[1], box.y0, box.y1)):
            delta = finish - origin

            if abs(delta) < 1e-12:
                if not minimum <= origin <= maximum:
                    low, high = 1.0, 0.0
                    break
            else:
                first, last = sorted(((minimum - origin) / delta, (maximum - origin) / delta))
                low, high = max(low, first), min(high, last)

        if low < high:
            hidden.append((low, high))

    intervals: list[tuple[float, float]] = []
    cursor = 0.0

    for low, high in sorted(hidden):
        if low > cursor:
            intervals.append((cursor, low))
        cursor = max(cursor, high)

    if cursor < 1:
        intervals.append((cursor, 1.0))

    dx, dy = end[0] - start[0], end[1] - start[1]
    return [((start[0] + low * dx, start[1] + low * dy), (start[0] + high * dx, start[1] + high * dy)) for low, high in intervals]
