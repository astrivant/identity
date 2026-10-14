"""
Preserve separately reviewed assessments with idempotent appends and validated provenance.
"""

from __future__ import annotations

import fcntl
import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from attrs import evolve

from witful.files import replace_file
from witful.knowledge.compiler import index
from witful.knowledge.contracts import as_data, structure
from witful.life.contracts import canonical, content_id, snapshot_identity
from witful.life.journal import capture_snapshot, read_archive
from witful.reflection.models import Assessment, Config, Review

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["config", "read", "record", "validate_assessments"]


def config(root: Path) -> Config:
    """
    Read optional collection settings; existing collections receive the documented defaults.

    Args:
        root (Path): Collection owning knowledge/reflection.json.

    Returns:
        Config: Validated bounded review settings.

    Raises:
        ValueError: Cadence or batch size is outside its supported range.
    """
    path = root / "knowledge/reflection.json"
    result = structure(json.loads(path.read_text()), Config) if path.exists() else Config()
    if not 1 <= result.interval_commits <= 100000 or not 1 <= result.batch_size <= 100:
        raise ValueError("Reflection requires 1-100000 commits and 1-100 decisions per batch")
    return result


def validate_assessments(assessments: tuple[Assessment, ...], decisions: set[str], concepts: set[str]) -> None:
    """
    Validate references, ordinal ratings, and evidence without inferring missing outcomes.

    Args:
        assessments (tuple[Assessment, ...]): Reviewed batch in stable order.
        decisions (set[str]): Known immutable Life event identifiers.
        concepts (set[str]): Concepts present in the captured current knowledge.

    Returns:
        None: Every rated observation has the required provenance.

    Raises:
        ValueError: References, order, scores, or supporting evidence are invalid.
    """
    identifiers = tuple(item.decision_id for item in assessments)
    if not identifiers or identifiers != tuple(sorted(set(identifiers))) or set(identifiers) - decisions:
        raise ValueError("Assessments require unique, sorted, existing decision IDs")

    for item in assessments:
        if any(not value.strip() for value in (item.current_choice, item.rationale, item.context_change)):
            raise ValueError("Assessments require a choice, rationale, and context-change statement")
        if item.knowledge_ids != tuple(sorted(set(item.knowledge_ids))) or set(item.knowledge_ids) - concepts:
            raise ValueError("Assessment knowledge references must be unique, sorted, and present in its snapshot")
        if item.current_support is not None and not item.knowledge_ids:
            raise ValueError("A present-support rating needs a current knowledge reference")

        for value in (item.current_support, item.observed_outcome, item.context_effect):
            if value is not None and (type(value) is not int or not -2 <= value <= 2):
                raise ValueError("Ratings must be integers from -2 to 2, or null for unknown")
        if item.observed_outcome is not None and not item.outcome_evidence.strip():
            raise ValueError("An observed outcome rating needs evidence")
        if item.context_effect is not None and not item.context_evidence.strip():
            raise ValueError("A context-change rating needs evidence")
        if any(not lesson.strip() for lesson in item.proposed_lessons):
            raise ValueError("Proposed lessons cannot be blank")


def read(root: Path) -> tuple[Review, ...]:
    """
    Validate the review chain against preserved decisions and each round's knowledge snapshot.

    Args:
        root (Path): Existing collection with an optional reflection journal.

    Returns:
        tuple[Review, ...]: Validated chronological rounds, or an empty history.

    Raises:
        ValueError: A hash chain, snapshot, timestamp, or reference is invalid.
    """
    path = root / "knowledge/reflections.jsonl"
    events = tuple(structure(json.loads(line), Review) for line in path.read_text().splitlines()) if path.exists() else ()
    decisions = {event.id for event in read_archive(root).events}
    previous = None
    seen: set[str] = set()

    for event in events:
        if event.id != content_id(event) or event.id in seen or event.previous != previous:
            raise ValueError("Broken reflection hash chain")
        if datetime.fromisoformat(event.recorded_at).tzinfo is None or re.fullmatch(r"[0-9a-f]{40,64}", event.revision) is None:
            raise ValueError("Review requires a timezone and resolved Git revision")
        concepts = set(index(snapshot_identity(event.snapshot))[0])
        validate_assessments(event.assessments, decisions, concepts)
        previous = event.id
        seen.add(event.id)
    return events


def record(root: Path, history: Path, assessments: tuple[Assessment, ...]) -> Review:
    """
    Append a complete review batch without changing Life decisions or accepting proposed lessons.

    Args:
        root (Path): Collection owning the journals and working knowledge sources.
        history (Path): Git checkout used for commit cadence; may hold encrypted collection sources.
        assessments (tuple[Assessment, ...]): Complete batch returned by the current review plan.

    Returns:
        Review: Existing identical round on retry, or a new content-addressed observation.

    Raises:
        ValueError: The batch differs from the plan, provenance fails, or review is disabled.
    """
    from witful.reflection.planning import plan, revision

    path = root / "knowledge/reflections.jsonl"
    with (root / ".reflection.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        settings = config(root)
        if not settings.enabled:
            raise ValueError("Reflection is disabled in knowledge/reflection.json")
        original = path.read_bytes() if path.exists() else None
        rounds = read(root)
        current = revision(history)
        snapshot = capture_snapshot(root)
        validate_assessments(assessments, {event.id for event in read_archive(root).events}, set(index(snapshot_identity(snapshot))[0]))

        # Retry identity includes the exact current knowledge bytes, not just a mutable Git label.
        if rounds and (rounds[-1].revision, rounds[-1].snapshot.id, rounds[-1].assessments) == (current, snapshot.id, assessments):
            return rounds[-1]
        expected = plan(root, history)["decision_ids"]
        if sorted(item.decision_id for item in assessments) != expected:
            raise ValueError("Review every requested decision; use null ratings for unavailable outcomes")
        event = Review("", rounds[-1].id if rounds else None, datetime.now(UTC).isoformat(), current, snapshot, assessments)
        event = evolve(event, id=content_id(event))
        separator = b"\n" if original and not original.endswith(b"\n") else b""
        replace_file(path, (original or b"") + separator + canonical(as_data(event)) + b"\n", expected=original)
        return event
