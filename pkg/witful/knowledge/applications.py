"""
Persist explicit application observations without inventing historical usage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING

from witful.files import replace_file
from witful.knowledge.compiler import index
from witful.knowledge.contracts import as_data, structure
from witful.knowledge.models import Application, Discipline

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from witful.knowledge.models import Identity

__all__ = ["append_application", "application_id", "effective_applications", "read_applications", "validate_applications"]


def application_id(application: Application) -> str:
    """
    Identify an observation independently of its recording time and input ordering.

    Args:
        application (Application): Application with canonical concept IDs; its ID is ignored.

    Returns:
        str: SHA-256 of task, context, concepts, outcome, and evidence.
    """
    payload = as_data(application)
    payload.pop("id")
    payload.pop("observed_at")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_applications(path: Path) -> tuple[Application, ...]:
    """
    Read the independent append-only usage journal without touching runtime databases.

    Args:
        path (Path): Versioned JSONL application journal.

    Returns:
        tuple[Application, ...]: Strictly structured observations; a new empty journal contains no inferred applications.
    """
    return tuple(structure(json.loads(line), Application) for line in path.read_text().splitlines() if line.strip())


def validate_applications(identity: Identity, applications: Sequence[Application]) -> None:
    """
    Bind usage evidence to actual concepts and reject ambiguous revisions.

    Args:
        identity (Identity): Compiled current hierarchy, retaining historical lessons.
        applications (Sequence[Application]): Full application history.

    Returns:
        None: All IDs, contexts, timestamps, and references are valid.

    Raises:
        ValueError: An observation has invalid data, an unknown reference, or a conflicting revision timestamp.
    """
    nodes, _ = index(identity)
    seen: set[str] = set()
    timestamps: set[tuple[str, str, datetime]] = set()

    for application in applications:
        observed = datetime.fromisoformat(application.observed_at)
        moment = (application.task, application.discipline_id, observed)

        if observed.tzinfo is None or moment in timestamps:
            raise ValueError("Application timestamps must be timezone-aware and unambiguous within a task/context")
        if application.id != application_id(application) or application.id in seen:
            raise ValueError("Invalid or duplicated application ID")
        if not application.task.strip() or not application.evidence.strip():
            raise ValueError("Applications require a task reference and explicit evidence")
        if not isinstance(nodes.get(application.discipline_id), Discipline):
            raise ValueError("Unknown application discipline")
        if not application.concept_ids or tuple(sorted(set(application.concept_ids))) != application.concept_ids:
            raise ValueError("Concept IDs must be nonempty, unique, and sorted")
        if set(application.concept_ids) - nodes.keys():
            raise ValueError("Application refers to an unknown concept")

        seen.add(application.id)
        timestamps.add(moment)


def effective_applications(applications: Sequence[Application]) -> tuple[Application, ...]:
    """
    Use the latest complete observation per task/context without erasing history.

    Args:
        applications (Sequence[Application]): Validated application journal.

    Returns:
        tuple[Application, ...]: Stable task/context observations; corrections replace counts rather than inflate them.
    """
    latest: dict[tuple[str, str], Application] = {}

    for application in sorted(applications, key=lambda item: (datetime.fromisoformat(item.observed_at), item.id)):
        latest[application.task, application.discipline_id] = application

    return tuple(latest[key] for key in sorted(latest))


def append_application(path: Path, application: Application, identity: Identity) -> str:
    """
    Append one reviewed usage record atomically under the caller's exclusive lock.

    Args:
        path (Path): Existing application journal.
        application (Application): New observation with its calculated ID.
        identity (Identity): Model used to validate every reference.

    Returns:
        str: Existing or newly written observation ID.

    Raises:
        ValueError: The complete resulting journal is invalid.
        RuntimeError: Another writer changed the journal before replacement.
    """
    original = path.read_bytes()
    existing = read_applications(path)
    validate_applications(identity, existing)
    validate_applications(identity, (application,))

    if any(item.id == application.id for item in existing):
        return application.id

    validate_applications(identity, (*existing, application))
    separator = b"\n" if original and not original.endswith(b"\n") else b""
    encoded = json.dumps(as_data(application), sort_keys=True, ensure_ascii=False).encode() + b"\n"
    replace_file(path, original + separator + encoded, expected=original)
    return application.id
