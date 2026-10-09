"""
Define immutable decision events and the exact knowledge inputs behind their views.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen

# Schema generation evaluates these annotations at runtime.
from sapience.knowledge.models import Application, Catalog  # noqa: TC001

__all__ = ["Archive", "Decision", "Event", "Snapshot"]


@frozen
class Decision:
    """
    Describe a reviewable choice using concise rationale and verifiable references.

    Attributes:
        key (str): Stable subject whose successive decisions form a revision chain.
        title (str): Human-readable choice label.
        task (str): Actual task or issue context.
        choice (str): Chosen behavior or disposition.
        rationale (str): Concise explanation of relevant constraints and tradeoffs.
        source (str): Evidence, user instruction, commit, or documentation reference.
        concept_ids (tuple[str, ...]): Concepts involved, including lemmas when applicable.
        alternatives (tuple[str, ...]): Documented alternatives, without inferred hidden deliberation.
        supersedes (str | None): Current event for this key being explicitly revised.
        status (Literal["accepted", "retired"]): Whether this choice remains in effect.
    """

    key: str
    title: str
    task: str
    choice: str
    rationale: str
    source: str
    concept_ids: tuple[str, ...]
    alternatives: tuple[str, ...] = ()
    supersedes: str | None = None
    status: Literal["accepted", "retired"] = "accepted"


@frozen
class Snapshot:
    """
    Preserve replay inputs independently of later edits to the current knowledge sources.

    Attributes:
        id (str): SHA-256 of all snapshot fields except this identifier.
        lessons_jsonl (str): Exact reviewed lesson journal contents.
        catalog (Catalog): Validated classification and relationship source.
        applications (tuple[Application, ...]): Complete observed-use journal at capture.
        renderer (tuple[str, ...]): Sorted code, lockfile, interpreter, platform, and library fingerprints.
        source_revision (str): Resolved Git source commit, or working-tree for current local inputs.
        version (Literal[1]): Supported snapshot schema version.
    """

    id: str
    lessons_jsonl: str
    catalog: Catalog
    applications: tuple[Application, ...]
    renderer: tuple[str, ...]
    source_revision: str = "working-tree"
    version: Literal[1] = 1


@frozen
class Event:
    """
    Link a recorded decision to its predecessor and reproducible input snapshot.

    Attributes:
        id (str): SHA-256 of all event fields except this identifier.
        previous (str | None): Immediately preceding event in the complete journal.
        recorded_at (str): Time of recording, not an invented historical decision date.
        snapshot_id (str): Content-addressed replay snapshot.
        decision (Decision): Choice and explicit revision metadata.
        version (Literal[1]): Supported event schema version.
    """

    id: str
    previous: str | None
    recorded_at: str
    snapshot_id: str
    decision: Decision
    version: Literal[1] = 1


@frozen
class Archive:
    """
    Transport a complete ordered history and its referenced snapshots between stores.

    Attributes:
        events (tuple[Event, ...]): Journal order, independent of wall-clock ordering.
        snapshots (tuple[Snapshot, ...]): Unique snapshots sorted by identifier.
    """

    events: tuple[Event, ...] = ()
    snapshots: tuple[Snapshot, ...] = ()
