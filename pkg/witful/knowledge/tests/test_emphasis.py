"""
Verify deterministic emphasis, revision handling, and nonoverlapping bounded layouts.
"""

from __future__ import annotations

import math
from itertools import combinations

import pytest
from attrs import evolve
from witful.knowledge.applications import application_id
from witful.knowledge.emphasis import emphasis_layout
from witful.knowledge.models import Application, Discipline, Identity, Skill
from witful.knowledge.rendering import graph_data


def _identity(count: int) -> Identity:
    """
    Create named synthetic disciplines without historical inferences.

    Args:
        count (int): Number of discipline and skill pairs.

    Returns:
        Identity: Complete immutable test hierarchy.
    """
    return Identity("root", "Example", tuple(Discipline(f"d{i}", f"Discipline {i}", (Skill(f"s{i}", f"Skill {i}"),)) for i in range(count)))


def _event(task: str, discipline: int, timestamp: str) -> Application:
    """
    Record a skill and its parent in one observation to exercise once-per-ancestor counting.

    Args:
        task (str): Explicit task identifier.
        discipline (int): Owning discipline index.
        timestamp (str): Recording time with UTC offset.

    Returns:
        Application: Valid content-addressed observation.
    """
    event = Application("", task, f"d{discipline}", (f"d{discipline}", f"s{discipline}"), "verified", "Synthetic evidence", timestamp)
    return evolve(event, id=application_id(event))


@pytest.mark.parametrize("count", [0, 1, 8, 12, 40])
def test_layout_is_bounded_repeatable_and_never_overlaps(count: int) -> None:
    """
    Handle empty, minimal, equal-weight, and larger collections without geometry drift.

    Args:
        count (int): Synthetic collection size.

    Returns:
        None: At most twelve circles fit the unit disk without overlap or changes to full graph data.
    """
    model = _identity(count)
    before = graph_data(model, ())
    bubbles = emphasis_layout(model, (), limit=12)
    assert len(bubbles) == min(count, 12)
    assert bubbles == emphasis_layout(model, (), limit=12)
    assert graph_data(model, ()) == before

    for bubble in bubbles:
        assert math.hypot(bubble.x, bubble.y) + bubble.radius <= 1.0000001
        assert 0.35 - 1e-9 <= bubble.opacity <= 1

    for left, right in combinations(bubbles, 2):
        assert math.dist((left.x, left.y), (right.x, right.y)) >= left.radius + right.radius + 0.025 - 1e-9

    if bubbles:
        assert (bubbles[0].x, bubbles[0].y, bubbles[0].opacity) == (0, 0, 1)


def test_recent_evidence_controls_emphasis_without_discarding_old_records() -> None:
    """
    Prefer current work over old frequency and treat revised tasks as one observation.

    Returns:
        None: Recent use ranks centrally; selection and fading leave the archive intact.
    """
    model = _identity(10)
    older = tuple(_event(f"old-{i}", 0, "2025-01-01T00:00:00Z") for i in range(20))
    first = _event("current", 1, "2026-01-01T00:00:00Z")
    revision = evolve(first, outcome="unassessed", evidence="Updated evidence", observed_at="2026-02-01T00:00:00Z")
    revision = evolve(revision, id=application_id(revision))
    events = (*older, first, revision)
    before = graph_data(model, events)
    bubbles = emphasis_layout(model, events)
    assert len(bubbles) == 10
    assert bubbles[0].id == "d1" and bubbles[0].score == 1
    assert bubbles[1].id == "d0" and 0 < bubbles[1].score < 0.01
    assert bubbles[0].radius > bubbles[1].radius
    assert any(bubble.opacity < 1 for bubble in bubbles[1:])
    assert bubbles == emphasis_layout(model, tuple(reversed(events)))
    assert graph_data(model, events) == before


@pytest.mark.parametrize("limit", [0, 13])
def test_layout_rejects_unreadable_limits(limit: int) -> None:
    """
    Keep the public viewport limit inside the documented readable range.

    Args:
        limit (int): Invalid requested cap.

    Returns:
        None: Invalid limits fail before calculating a layout.
    """
    with pytest.raises(ValueError, match="between one and twelve"):
        emphasis_layout(_identity(1), (), limit=limit)
