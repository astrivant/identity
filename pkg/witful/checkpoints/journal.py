"""
Append explicit Git boundaries with a validated hash chain and idempotent retry semantics.
"""

from __future__ import annotations

import fcntl
import json
import re
import subprocess
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from attrs import evolve

from witful.checkpoints.models import Checkpoint
from witful.checkpoints.snapshot import digest, snapshot
from witful.files import replace_file
from witful.knowledge.applications import read_applications
from witful.knowledge.compiler import compile_identity
from witful.knowledge.contracts import as_data, structure
from witful.knowledge.models import Catalog
from witful.lessons import read_journal

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = ["checkpoint_id", "read", "record", "validate"]
_HASH = re.compile(r"[0-9a-f]{64}")


def checkpoint_id(event: Checkpoint) -> str:
    """
    Bind project metadata and all snapshot fields to an immutable identifier.

    Args:
        event (Checkpoint): Record whose current ID is ignored.

    Returns:
        str: Canonical content digest.
    """
    value = as_data(event)
    value.pop("id")
    return digest(value)


def validate(events: Sequence[Checkpoint]) -> None:
    """
    Reject broken chronology, altered content, duplicate facts, and ambiguous states.

    Args:
        events (Sequence[Checkpoint]): Complete ordered history.

    Returns:
        None: The hash chain and every snapshot meet the checkpoint contract.

    Raises:
        ValueError: A record violates a structural or chronological invariant.
    """
    previous: str | None = None
    seen: set[str] = set()

    for event in events:
        if event.id != checkpoint_id(event) or event.id in seen or event.previous != previous:
            raise ValueError("Invalid checkpoint content or history chain")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}", event.project) or ".." in event.project.split("/"):
            raise ValueError("Project aliases require 1-128 letters, digits, dots, slashes, underscores, or hyphens")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", event.revision):
            raise ValueError("Checkpoint revision must be a full Git commit ID")
        if datetime.fromisoformat(event.recorded_at).tzinfo is None:
            raise ValueError("Checkpoint recording time must include a timezone")
        identifiers = [state.id for state in event.skills]

        if identifiers != sorted(set(identifiers)) or any(not state.id.strip() or not state.name.strip() for state in event.skills):
            raise ValueError("Checkpoint skills require sorted unique IDs and nonempty names")

        for state in event.skills:
            for facts in (state.lessons, state.uses):
                keys = [fact.id for fact in facts]

                if keys != sorted(set(keys)) or any(not fact.id.strip() or not _HASH.fullmatch(fact.digest) for fact in facts):
                    raise ValueError("Checkpoint facts require unique sorted keys and SHA-256 digests")

        previous = event.id
        seen.add(event.id)


def read(path: Path) -> tuple[Checkpoint, ...]:
    """
    Read an empty or existing source journal without creating a database.

    Args:
        path (Path): Collection-owned checkpoint JSONL file.

    Returns:
        tuple[Checkpoint, ...]: Complete validated history; absence means no recorded boundaries.
    """
    events = (
        tuple(structure(json.loads(line), Checkpoint) for line in path.read_text().splitlines() if line.strip()) if path.exists() else ()
    )
    validate(events)
    return events


def record(root: Path, project: Path, alias: str) -> Checkpoint:
    """
    Append one explicit project boundary using current reviewed collection inputs.

    Args:
        root (Path): Collection containing lessons and application journals.
        project (Path): Existing Git checkout to identify, without reading its source or remote configuration.
        alias (str): Stable project identifier selected by the caller.

    Returns:
        Checkpoint: Newly appended record or the last record for an identical immediate retry.

    Raises:
        ValueError: Git has no committed HEAD or the source evidence is invalid.
        RuntimeError: A source journal changes concurrently with the atomic replacement.
    """
    result = subprocess.run(
        ["git", "-C", str(project.resolve()), "rev-parse", "--verify", "HEAD^{commit}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    if result.returncode:
        raise ValueError("Checkpoint project must be an existing Git checkout with a committed HEAD")

    # Reuse the collection's writer lock so application updates cannot race snapshot compilation.
    with (root / ".applications.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "knowledge/checkpoints.jsonl"
        original = path.read_bytes() if path.exists() else None
        events = read(path)
        catalog = structure(json.loads((root / "knowledge/catalog.json").read_text()), Catalog)
        identity = compile_identity(read_journal(root / "lessons.jsonl"), catalog)
        skills = snapshot(identity, read_applications(root / "knowledge/applications.jsonl"))
        revision = result.stdout.strip()

        # Returning to a project after another visit is a new boundary, even at the same commit.
        if events and (events[-1].project, events[-1].revision, events[-1].skills) == (alias, revision, skills):
            return events[-1]

        event = Checkpoint("", events[-1].id if events else None, alias, revision, datetime.now(UTC).isoformat(), skills)
        event = evolve(event, id=checkpoint_id(event))
        validate((*events, event))
        content = (original or b"").rstrip(b"\n")
        content += (b"\n" if content else b"") + json.dumps(as_data(event), sort_keys=True).encode() + b"\n"
        replace_file(path, content, expected=original)
        return event
