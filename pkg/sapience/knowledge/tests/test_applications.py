"""
Verify append-only application history and evidence-based counting contracts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pytest
from attrs import evolve
from sapience.knowledge.applications import append_application, application_id, read_applications, validate_applications
from sapience.knowledge.metrics import affinity, graph_edges, usage
from sapience.knowledge.models import Application, Discipline, Identity, Lemma, Lesson, Skill

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def hierarchy() -> Identity:
    """
    Supply two disciplines and one decomposed teaching for evidence tests.

    Returns:
        Identity: Synthetic collection with stable IDs and explicit ownership.
    """
    lesson = Lesson(
        "lesson",
        "Lesson",
        "Use contracts.",
        "Fixture",
        "2026-01-01T00:00:00Z",
        lemmas=(Lemma("lemma", "Lemma", "Validate inputs.", "Fixture"),),
    )
    return Identity("root", "Example", (Discipline("a", "A", (Skill("sa", "SA", (lesson,)),)), Discipline("b", "B", (Skill("sb", "SB"),))))


def event(
    task: str,
    concepts: tuple[str, ...],
    outcome: Literal["unassessed", "verified", "unsuccessful"] = "verified",
    timestamp: str = "2026-01-01T00:00:00Z",
    context: str = "a",
) -> Application:
    """
    Construct a valid application with a content-derived ID.

    Args:
        task (str): Unique task reference.
        concepts (tuple[str, ...]): Explicit uses, normalized to stable ordering.
        outcome (Literal["unassessed", "verified", "unsuccessful"]): Reported result.
        timestamp (str): Recording time.
        context (str): Application discipline.

    Returns:
        Application: Synthetic sourced observation.
    """
    value = Application("", task, context, tuple(sorted(concepts)), outcome, "Synthetic validation", timestamp)
    return evolve(value, id=application_id(value))


def test_upward_rollup_counts_once_without_guessing_children(hierarchy: Identity) -> None:
    """
    Count ancestors once even when the application names multiple levels of the same path.

    Args:
        hierarchy (Identity): Test hierarchy.

    Returns:
        None: Direct parents do not imply use of any unrecorded descendant.
    """
    counts = usage(hierarchy, (event("t", ("lesson", "sa")),))
    assert counts["root"].applications == counts["sa"].applications == counts["lesson"].applications == 1
    assert counts["lemma"].applications == counts["b"].applications == 0


def test_revisions_and_identical_reruns_do_not_inflate_counts(hierarchy: Identity, tmp_path: Path) -> None:
    """
    Preserve history while replacing the effective observation for a task and context.

    Args:
        hierarchy (Identity): Test hierarchy.
        tmp_path (Path): Isolated journal directory.

    Returns:
        None: Repeated observations preserve bytes and corrections count once with their latest full set.
    """
    journal = tmp_path / "applications.jsonl"
    journal.touch()
    first = event("t", ("sa",), "unassessed")
    append_application(journal, first, hierarchy)
    original = journal.read_bytes()
    append_application(journal, evolve(first, observed_at="2026-01-02T00:00:00Z"), hierarchy)
    assert journal.read_bytes() == original
    correction = event("t", ("sb",), timestamp="2026-01-03T00:00:00Z")
    append_application(journal, correction, hierarchy)
    records = read_applications(journal)
    assert len(records) == 2
    counts = usage(hierarchy, records)
    assert counts["root"].applications == counts["sb"].verified == 1
    assert counts["sa"].applications == 0


@pytest.mark.parametrize("joint,left,right,expected", [(0, 0, 0, 0.0), (1, 2, 2, 0.5), (2, 2, 2, 1.0), (1, 1, 4, 0.5)])
def test_affinity_is_normalized(joint: int, left: int, right: int, expected: float) -> None:
    """
    Check normalized binary incidence similarity against independently computed examples.

    Args:
        joint (int): Shared observations.
        left (int): First marginal.
        right (int): Second marginal.
        expected (float): Analytical expected affinity.

    Returns:
        None: Affinity stays in its documented scale.
    """
    assert affinity(joint, left, right) == expected


def test_observed_graph_separates_verification_and_transfer(hierarchy: Identity) -> None:
    """
    Derive connections from verified co-use and preserve unsuccessful applications separately.

    Args:
        hierarchy (Identity): Test hierarchy.

    Returns:
        None: Weights represent normalized evidence and cross-discipline transfer shares.
    """
    records = (
        event("one", ("sa", "sb")),
        event("two", ("sa",)),
        event("three", ("sb",), context="b"),
        event("four", ("sa", "sb"), "unsuccessful"),
    )
    edges = graph_edges(hierarchy, records)
    pair = next(edge for edge in edges if edge.kind == "co-use")
    assert (pair.applications, pair.verified, pair.strength) == (2, 1, 0.5)
    transfer = next(edge for edge in edges if edge.kind == "observed-transfer")
    assert (transfer.source, transfer.target, transfer.strength) == ("sb", "a", 0.5)
    assert graph_edges(hierarchy, records) == graph_edges(hierarchy, tuple(reversed(records)))


def test_invalid_observations_fail_without_writing(hierarchy: Identity, tmp_path: Path) -> None:
    """
    Refuse fabricated IDs, missing concepts, ambiguous times, and invalid contexts.

    Args:
        hierarchy (Identity): Test hierarchy.
        tmp_path (Path): Isolated journal directory.

    Returns:
        None: Validation precedes every durable append.
    """
    journal = tmp_path / "applications.jsonl"
    journal.touch()
    candidates = (
        event("t", ("unknown",)),
        event("t", ("sa",), context="sa"),
        event("t", ("sa",), timestamp="2026-01-01"),
        evolve(event("t", ("sa",)), id="fake"),
        event("t", ()),
    )

    for candidate in candidates:
        with pytest.raises(ValueError):
            append_application(journal, candidate, hierarchy)
        assert journal.read_bytes() == b""

    with pytest.raises(ValueError, match="unambiguous"):
        validate_applications(hierarchy, (event("t", ("sa",)), event("t", ("sb",))))

    with pytest.raises(ValueError):
        affinity(2, 1, 4)
