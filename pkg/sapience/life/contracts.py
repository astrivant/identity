"""
Validate hash chains and project current decisions without modifying their history.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import TYPE_CHECKING

from sapience.knowledge.applications import validate_applications
from sapience.knowledge.compiler import compile_identity, index
from sapience.knowledge.contracts import as_data
from sapience.lessons import parse_journal

if TYPE_CHECKING:
    from sapience.knowledge.models import Identity
    from sapience.life.models import Archive, Event, Snapshot

__all__ = ["canonical", "content_id", "current_decisions", "snapshot_identity", "validate_archive"]


def canonical(value: object) -> bytes:
    """
    Encode JSON with stable field order and no runtime-dependent whitespace.

    Args:
        value (object): JSON-compatible value.

    Returns:
        bytes: Canonical UTF-8 representation used by hashing and persistence.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def content_id(value: object) -> str:
    """
    Fingerprint the complete source record except its own identifier.

    Args:
        value (object): Attrs event or snapshot with an id field.

    Returns:
        str: SHA-256 digest, including event timestamps and parent references.
    """
    payload = as_data(value)
    payload.pop("id")
    return hashlib.sha256(canonical(payload)).hexdigest()


def snapshot_identity(snapshot: Snapshot) -> Identity:
    """
    Validate and compile historical knowledge without reading today's source tree.

    Args:
        snapshot (Snapshot): Content-addressed knowledge inputs.

    Returns:
        Identity: Validated hierarchy with its application journal checked against those concepts.
    """
    if snapshot.id != content_id(snapshot):
        raise ValueError("Snapshot content does not match its identifier")

    identity = compile_identity(parse_journal(snapshot.lessons_jsonl), snapshot.catalog)
    validate_applications(identity, snapshot.applications)
    return identity


def validate_archive(archive: Archive) -> None:
    """
    Reject altered records, dangling sources, and ambiguous revisions before projection or seeding.

    Args:
        archive (Archive): Complete source history and snapshot set.

    Returns:
        None: All events form one causal chain and every decision has valid historical concept references.

    Raises:
        ValueError: IDs, chain links, revisions, timestamps, or source references are invalid.
    """
    snapshots = {snapshot.id: snapshot for snapshot in archive.snapshots}

    if len(snapshots) != len(archive.snapshots):
        raise ValueError("Duplicate snapshots in the audit archive")

    concepts = {identifier: index(snapshot_identity(snapshot))[0] for identifier, snapshot in snapshots.items()}
    seen: set[str] = set()
    heads: dict[str, Event] = {}
    previous: str | None = None

    for event in archive.events:
        decision = event.decision

        if event.id != content_id(event) or event.id in seen or event.previous != previous:
            raise ValueError("Broken decision event hash chain")
        if datetime.fromisoformat(event.recorded_at).tzinfo is None:
            raise ValueError("Decision recording time must include a timezone")
        if event.snapshot_id not in snapshots:
            raise ValueError("Decision refers to a missing snapshot")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,199}", decision.key):
            raise ValueError("Decision keys must be stable nonempty identifiers, at most 200 characters")
        if any(not value.strip() for value in (decision.title, decision.task, decision.choice, decision.rationale, decision.source)):
            raise ValueError("Decisions require a title, task, choice, rationale, and source")
        if not decision.concept_ids or decision.concept_ids != tuple(sorted(set(decision.concept_ids))):
            raise ValueError("Decision concept IDs must be nonempty, unique, and sorted")
        if set(decision.concept_ids) - concepts[event.snapshot_id].keys():
            raise ValueError("Decision refers to an unknown concept in its recorded snapshot")
        if any(not value.strip() for value in decision.alternatives):
            raise ValueError("Documented alternatives cannot be blank")

        # Revision identity is explicit; timestamps cannot silently choose a winner between conflicting branches.
        head = heads.get(decision.key)
        expected = head.id if head else None

        if decision.supersedes != expected or (head is None and decision.status == "retired"):
            raise ValueError("A revision must supersede the current event for the same decision key")

        heads[decision.key] = event
        seen.add(event.id)
        previous = event.id


def current_decisions(archive: Archive) -> tuple[Event, ...]:
    """
    Project one latest disposition per subject while retaining retired choices for inspection.

    Args:
        archive (Archive): Validated history, or a prefix selected for historical replay.

    Returns:
        tuple[Event, ...]: Latest event per key in stable key order, including explicit retirements.
    """
    validate_archive(archive)
    heads = {event.decision.key: event for event in archive.events}
    return tuple(heads[key] for key in sorted(heads))
