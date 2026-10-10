"""
Draw the fitted Gaussian's principal directions with true-distance tips and exterior labels.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from attrs import frozen

from witful.knowledge.map_labels import visible_segments

if TYPE_CHECKING:
    from collections.abc import Sequence

    from matplotlib.axes import Axes
    from matplotlib.transforms import Bbox

__all__ = ["GaussianAxis", "draw_principal_axes", "principal_axes"]

_TIP_SIGMAS = 2.7
_LABEL_RADIUS = 1.05
_LABEL_GAP = 0.08
_INK = "#697783"


@frozen
class GaussianAxis:
    """
    Keep statistical endpoints distinct from labels displaced for readability.

    Attributes:
        name (str): Major or Minor principal direction.
        start (tuple[float, float]): Negative endpoint at the specified standardized distance.
        end (tuple[float, float]): Positive endpoint at the specified standardized distance.
        label_start (tuple[float, float]): Negative label beyond the bubble-packing boundary.
        label_end (tuple[float, float]): Positive label beyond the bubble-packing boundary.
    """

    name: str
    start: tuple[float, float]
    end: tuple[float, float]
    label_start: tuple[float, float]
    label_end: tuple[float, float]


def principal_axes(profile: tuple[float, float, float, float, float, float]) -> tuple[GaussianAxis, ...]:
    """
    Place tips on covariance eigenvectors and labels outside the unit-circle bubble layout.

    Args:
        profile (tuple[float, float, float, float, float, float]): Valid fitted center, positive principal variances, cosine, and sine.

    Returns:
        tuple[GaussianAxis, ...]: Major and minor guides sharing the ellipse's center and rotation.
    """
    x, y, major, minor, cosine, sine = profile
    guides = []

    for name, variance, direction in (("Major", major, (cosine, sine)), ("Minor", minor, (-sine, cosine))):
        distance = _TIP_SIGMAS * math.sqrt(variance)
        tips = []
        labels = []

        for sign in (-1, 1):
            dx, dy = sign * direction[0], sign * direction[1]
            tips.append((x + distance * dx, y + distance * dy))

            # Intersect this outward ray with the packing boundary without moving its statistical tip.
            projection = x * dx + y * dy
            boundary = -projection + math.sqrt(max(0.0, projection**2 + _LABEL_RADIUS**2 - x**2 - y**2))
            offset = max(distance, boundary) + _LABEL_GAP
            labels.append((x + offset * dx, y + offset * dy))

        guides.append(GaussianAxis(name, tips[0], tips[1], labels[0], labels[1]))

    return tuple(guides)


def draw_principal_axes(axis: Axes, guides: Sequence[GaussianAxis], exclusions: Sequence[Bbox]) -> None:
    """
    Keep muted guides behind bubble lettering and mark the exact standardized endpoints.

    Args:
        axis (Axes): Final map viewport with its renderer initialized.
        guides (Sequence[GaussianAxis]): Fitted directions and exterior label locations.
        exclusions (Sequence[Bbox]): Bubble lettering and mean-marker clearances in data coordinates.

    Returns:
        None: Adds labels, clipped lines, and endpoint markers without changing the fit or bubble geometry.
    """
    boxes = list(exclusions)

    for guide in guides:
        key = guide.name.lower()

        for sign, tip, label in (("-", guide.start, guide.label_start), ("+", guide.end, guide.label_end)):
            text = axis.text(
                *label,
                f"{guide.name} axis\n{sign}{_TIP_SIGMAS:g} SD",
                ha="center",
                va="center",
                multialignment="center",
                fontsize=8.5,
                color=_INK,
                alpha=1.0,
                zorder=12,
                gid=f"gaussian-axis-label:{key}:{sign}",
            )
            boxes.append(text.get_window_extent().padded(4).transformed(axis.transData.inverted()))
            axis.scatter(*tip, marker="D", s=15, color=_INK, zorder=4, gid=f"gaussian-axis-tip:{key}:{sign}")

        # Dotted leaders distinguish displaced labels from the solid, measured principal-axis span.
        for start, end, linestyle in (
            (guide.start, guide.end, "-"),
            (guide.start, guide.label_start, ":"),
            (guide.end, guide.label_end, ":"),
        ):
            for left, right in visible_segments(start, end, boxes):
                axis.plot(
                    [left[0], right[0]],
                    [left[1], right[1]],
                    color=_INK,
                    linewidth=0.8,
                    alpha=0.65,
                    linestyle=linestyle,
                    zorder=0,
                    gid=f"gaussian-axis-guide:{key}",
                )
