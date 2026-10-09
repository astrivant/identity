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

_LIMIT = 8
_HALF_LIFE_DAYS = 30.0
_GAP = 0.025
_FADE_START = 0.8


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
            return tuple(
                Bubble(
                    key,
                    scores[key],
                    x,
                    y,
                    radius,
                    1 - 0.65 * max(0.0, min(1.0, (math.hypot(x, y) + radius - _FADE_START) / (1 - _FADE_START))),
                )
                for key, (x, y), radius in zip(selected, points, radii, strict=True)
            )

    raise RuntimeError("Could not pack the bounded emphasis map")
