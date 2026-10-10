"""
Show fitted Gaussian directions with compact outer spokes clear of the bubbles.
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

    from witful.knowledge.emphasis import Bubble

__all__ = ["GaussianAxis", "draw_principal_axes", "principal_axes"]

_TIP_SIGMAS = 2.7
_BUBBLE_CLEARANCE = 0.05
_TICK_LENGTH = 0.07
_INK = "#697783"


@frozen
class GaussianAxis:
    """
    Locate the inner endpoints of two outward spokes on a fitted principal axis.

    Attributes:
        name (str): Major or Minor principal direction.
        start (tuple[float, float]): Negative endpoint beyond the standardized threshold and nearby bubbles.
        end (tuple[float, float]): Positive endpoint beyond the standardized threshold and nearby bubbles.
    """

    name: str
    start: tuple[float, float]
    end: tuple[float, float]


def principal_axes(profile: tuple[float, float, float, float, float, float], bubbles: Sequence[Bubble] = ()) -> tuple[GaussianAxis, ...]:
    """
    Place outer spokes on covariance eigenvectors without reserving space for redundant labels.

    Args:
        profile (tuple[float, float, float, float, float, float]): Valid fitted center, positive principal variances, cosine, and sine.
        bubbles (Sequence[Bubble]): Visible circles whose padded boundaries the spokes must clear.

    Returns:
        tuple[GaussianAxis, ...]: Major and minor guides sharing the ellipse's center and rotation.
    """
    x, y, major, minor, cosine, sine = profile
    guides = []

    for name, variance, direction in (("Major", major, (cosine, sine)), ("Minor", minor, (-sine, cosine))):
        distance = _TIP_SIGMAS * math.sqrt(variance)
        tips = []

        for sign in (-1, 1):
            dx, dy = sign * direction[0], sign * direction[1]
            offset = distance

            # Intersect this outward ray with actual padded bubbles, not a larger enclosing circle.
            # Moving beyond the furthest intersection preserves collinearity without adding unnecessary margins.
            for bubble in bubbles:
                bx, by = bubble.x - x, bubble.y - y
                projection = bx * dx + by * dy
                discriminant = (bubble.radius + _BUBBLE_CLEARANCE) ** 2 - (bx * bx + by * by - projection**2)

                if discriminant >= 0:
                    offset = max(offset, projection + math.sqrt(discriminant))

            tips.append((x + offset * dx, y + offset * dy))

        guides.append(GaussianAxis(name, tips[0], tips[1]))

    return tuple(guides)


def draw_principal_axes(axis: Axes, guides: Sequence[GaussianAxis], exclusions: Sequence[Bbox]) -> None:
    """
    Draw short outer spokes collinear with the fitted axes, leaving the center and labels clear.

    Args:
        axis (Axes): Final map viewport with its renderer initialized.
        guides (Sequence[GaussianAxis]): Endpoints beyond the statistical threshold and nearby bubble boundaries.
        exclusions (Sequence[Bbox]): Bubble lettering and mean-marker clearances in data coordinates.

    Returns:
        None: Adds separated spokes without axis labels, central lines, markers, or changes to the fitted distribution.
    """
    for guide in guides:
        key = guide.name.lower()
        length = math.dist(guide.start, guide.end)
        dx, dy = ((end - start) / length for start, end in zip(guide.start, guide.end, strict=True))

        # Both segments extend away from the mean along the same principal direction.
        for sign, direction, start in (("-", -1, guide.start), ("+", 1, guide.end)):
            end = (start[0] + direction * _TICK_LENGTH * dx, start[1] + direction * _TICK_LENGTH * dy)

            for left, right in visible_segments(start, end, exclusions):
                axis.plot(
                    [left[0], right[0]],
                    [left[1], right[1]],
                    color=_INK,
                    linewidth=0.8,
                    alpha=0.65,
                    solid_capstyle="round",
                    zorder=0,
                    gid=f"gaussian-axis-tick:{key}:{sign}",
                )
