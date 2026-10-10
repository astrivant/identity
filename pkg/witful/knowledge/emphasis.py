"""
Derive a bounded view of current working emphasis without altering the knowledge archive.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING

from attrs import frozen

from witful.knowledge.applications import effective_applications, validate_applications
from witful.knowledge.compiler import index, lineage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from witful.knowledge.models import Application, Identity

__all__ = ["Bubble", "emphasis_layout"]

_LIMIT = 12
_HALF_LIFE_DAYS = 30.0
_GAP = 0.025
_OPACITY_SIGMAS = 1.75
_OPACITY_FALLOFF_SCALE = 2.0
_MIN_OPACITY = 0.35


@frozen
class Bubble:
    """
    Describe one discipline's immutable placement in a unit-circle viewport.

    Attributes:
        id (str): Canonical discipline ID; hidden disciplines remain in the source hierarchy.
        score (float): Sum of distinct task/context uses weighted by recording recency.
        x (float): Horizontal center.
        y (float): Vertical center.
        radius (float): Circle radius, decreasing with relative recent use.
        opacity (float): Peripheral display opacity; never a knowledge-retention measure.
    """

    id: str
    score: float
    x: float
    y: float
    radius: float
    opacity: float


def _pack(radii: Sequence[float], priorities: Sequence[float]) -> list[tuple[float, float]]:
    """
    Search deterministic polar slots while excluding overlap and viewport overflow.

    Args:
        radii (Sequence[float]): Circle radii, ordered by decreasing working emphasis.
        priorities (Sequence[float]): Relative recent-use weights between zero and one.

    Returns:
        list[tuple[float, float]]: Complete placements, or an empty list if this scale cannot fit.
    """
    points: list[tuple[float, float]] = []

    for ordinal, (radius, priority) in enumerate(zip(radii, priorities, strict=True)):
        desired = 0.0 if ordinal == 0 else (1 - priority) * (1 - radius)
        phase = ordinal * math.pi * (3 - math.sqrt(5))
        candidates = [(0.0, 0.0)]

        for ring in range(1, 65):
            distance = ring / 64 * (1 - radius)

            for step in range(96):
                angle = phase + step * math.tau / 96
                candidates.append((distance * math.cos(angle), distance * math.sin(angle)))
        candidates.sort(key=lambda point: (abs(math.hypot(*point) - desired), math.hypot(*point)))
        selected = next(
            (
                point
                for point in candidates
                if all(math.dist(point, previous) >= radius + radii[index] + _GAP for index, previous in enumerate(points))
            ),
            None,
        )

        if selected is None:
            return []

        points.append(selected)

    return points


def _gaussian_profile(points: Sequence[tuple[float, float]], weights: Sequence[float]) -> tuple[float, float, float, float, float, float]:
    """
    Fit the weighted, rotated two-dimensional Gaussian used by the map renderer.

    Args:
        points (Sequence[tuple[float, float]]): Bubble centers in viewport coordinates.
        weights (Sequence[float]): Nonnegative emphasis weights for the centers.

    Returns:
        tuple[float, float, float, float, float, float]: Weighted center, principal variances,
            and the principal-axis cosine and sine.

    Raises:
        ValueError: If the point and weight sequences differ in length or are empty.
    """
    if len(points) != len(weights):
        raise ValueError("Gaussian profile requires one weight per point")
    if not points:
        raise ValueError("Gaussian profile requires at least one point")

    total = sum(weights) or float(len(points))
    normalized = tuple(weight / total for weight in weights) if sum(weights) else (1 / len(points),) * len(points)
    mean_x = sum(point[0] * weight for point, weight in zip(points, normalized, strict=True))
    mean_y = sum(point[1] * weight for point, weight in zip(points, normalized, strict=True))
    centered = tuple((point[0] - mean_x, point[1] - mean_y) for point in points)
    covariance_xx = sum(vector[0] ** 2 * weight for vector, weight in zip(centered, normalized, strict=True))
    covariance_xy = sum(vector[0] * vector[1] * weight for vector, weight in zip(centered, normalized, strict=True))
    covariance_yy = sum(vector[1] ** 2 * weight for vector, weight in zip(centered, normalized, strict=True))
    covariance_xx += 1e-6
    covariance_yy += 1e-6
    trace = covariance_xx + covariance_yy
    spread = math.sqrt((covariance_xx - covariance_yy) ** 2 + 4 * covariance_xy**2)
    major = max((trace + spread) / 2, 1e-6)
    minor = max((trace - spread) / 2, 1e-6)
    angle = 0.5 * math.atan2(2 * covariance_xy, covariance_xx - covariance_yy)
    return mean_x, mean_y, major, minor, math.cos(angle), math.sin(angle)


def _gaussian_distance(point: tuple[float, float], profile: tuple[float, float, float, float, float, float]) -> float:
    """
    Measure one point in the fitted Gaussian's rotated Mahalanobis coordinates.

    Args:
        point (tuple[float, float]): Point in viewport coordinates.
        profile (tuple[float, float, float, float, float, float]): Profile from ``_gaussian_profile``.

    Returns:
        float: Nonnegative distance from the weighted Gaussian center.
    """
    mean_x, mean_y, major, minor, cosine, sine = profile
    vector = (point[0] - mean_x, point[1] - mean_y)
    major_axis = cosine * vector[0] + sine * vector[1]
    minor_axis = -sine * vector[0] + cosine * vector[1]
    return math.sqrt(major_axis**2 / major + minor_axis**2 / minor)


def _gaussian_opacity(points: Sequence[tuple[float, float]], weights: Sequence[float]) -> tuple[float, ...]:
    """
    Convert rotated two-dimensional Gaussian distance into bounded bubble opacity.

    Args:
        points (Sequence[tuple[float, float]]): Packed bubble centers.
        weights (Sequence[float]): Nonnegative emphasis weights for the centers.

    Returns:
        tuple[float, ...]: Opacity values, with one value per center.

    Raises:
        ValueError: If the point and weight sequences differ in length.
    """
    if not points:
        return ()
    profile = _gaussian_profile(points, weights)

    opacities = []
    for point in points:
        distance = _gaussian_distance(point, profile)
        # Keep the selection boundary unchanged while spreading the same fade over twice the distance.
        fade = min(1.0, distance / (_OPACITY_SIGMAS * _OPACITY_FALLOFF_SCALE))
        opacities.append(1 - (1 - _MIN_OPACITY) * fade)
    opacities[0] = 1.0
    return tuple(opacities)


def emphasis_layout(identity: Identity, applications: Sequence[Application], *, limit: int = _LIMIT) -> tuple[Bubble, ...]:
    """
    Pack the most recently active disciplines with deterministic decay and bounded geometry.

    Args:
        identity (Identity): Complete validated hierarchy, retained unchanged.
        applications (Sequence[Application]): Full journal; revisions count once per task/context.
        limit (int): Maximum displayed disciplines, between one and twelve; defaults to eight.

    Returns:
        tuple[Bubble, ...]: Ranked nonoverlapping circles, with the strongest emphasis at the center.

    Raises:
        ValueError: Inputs are invalid or the requested limit exceeds the readable bound.
        RuntimeError: Bounded packing could not fit the selected circles.
    """
    if not 1 <= limit <= 12:
        raise ValueError("The emphasis map limit must be between one and twelve")

    validate_applications(identity, applications)
    _, parents = index(identity)
    events = effective_applications(applications)
    scores = {discipline.id: 0.0 for discipline in identity.disciplines}
    last_use = dict.fromkeys(scores, float("-inf"))
    observed = {event.id: datetime.fromisoformat(event.observed_at).timestamp() for event in events}
    latest = max(observed.values(), default=0.0)

    # Use the latest recorded event as the time origin, so identical evidence never ages during a rebuild.
    for event in sorted(events, key=lambda item: item.id):
        reached = {ancestor for concept in event.concept_ids for ancestor in lineage(concept, parents)}
        reached.add(event.discipline_id)
        age_days = (latest - observed[event.id]) / 86400
        weight = 2 ** (-age_days / _HALF_LIFE_DAYS)

        for identifier in reached & scores.keys():
            scores[identifier] += weight
            last_use[identifier] = max(last_use[identifier], observed[event.id])

    selected = sorted(scores, key=lambda key: (-scores[key], -last_use[key], key))[:limit]

    if not selected:
        return ()

    maximum = max(scores.values())
    priorities = [scores[key] / maximum if maximum else 0.0 for key in selected]
    largest = min(0.30, 0.75 / math.sqrt(len(selected)))
    initial = [largest * (0.60 + 0.40 * math.sqrt(priority)) for priority in priorities]

    # Uniform bounded shrinkage handles equal-weight crowds without collision jitter or random seeds.
    for attempt in range(12):
        radii = [radius * 0.95**attempt for radius in initial]
        points = _pack(radii, priorities)

        if points:
            opacities = _gaussian_opacity(points, tuple(scores[key] for key in selected))
            return tuple(
                Bubble(
                    key,
                    scores[key],
                    x,
                    y,
                    radius,
                    opacity,
                )
                for key, (x, y), radius, opacity in zip(selected, points, radii, opacities, strict=True)
            )

    raise RuntimeError("Could not pack the bounded emphasis map")
