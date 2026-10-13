"""
Define closed review contracts independent of filesystem, clock, and runtime state.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen


@frozen
class Workspace:
    """
    Bind a review to an explicitly inspected Git checkout.

    Attributes:
        path (str): Absolute checkout path, retained only in private local audit state.
        revision (str): Full committed HEAD of an existing checkout.
        digest (str): Digest of index entries and tracked/nonignored working files.
    """

    path: str
    revision: str
    digest: str


@frozen
class Entry:
    """
    Preserve one hierarchy node and its independently reviewed disposition.

    Attributes:
        id (str): Stable concept identifier.
        parent (str | None): Canonical owner, absent only for the identity root.
        kind (str): Model type, including Identity, Discipline, Skill, Lesson, and Insight.
        name (str): Current human-readable label.
        statement (str): Current teaching text, empty for organizational nodes.
        source (str): Teaching provenance, empty for organizational nodes.
        status (Literal["pending", "satisfied", "not_applicable", "blocked", "historical"]): Explicit disposition.
        reason (str): Applicability, outcome, blocker, or supersession explanation.
        evidence (tuple[str, ...]): Reviewed references supporting a satisfied entry.
        next_action (str): Concrete remaining action when blocked.
    """

    id: str
    parent: str | None
    kind: str
    name: str
    statement: str
    source: str
    status: Literal["pending", "satisfied", "not_applicable", "blocked", "historical"] = "pending"
    reason: str = ""
    evidence: tuple[str, ...] = ()
    next_action: str = ""


@frozen
class Audit:
    """
    Record review coverage without claiming independent proof of its evidence.

    Attributes:
        task (str): Explicit task or runtime turn binding.
        identity (str): Stable owning collection ID.
        hierarchy_digest (str): Canonical digest of every node and reuse relation.
        workspaces (tuple[Workspace, ...]): Explicitly selected checkout snapshots.
        entries (tuple[Entry, ...]): Complete hierarchy, including retained historical teachings.
        outcome (Literal["complete", "handoff"]): Requested completion or acknowledged incomplete handoff.
        handoff_reason (str): Explanation for an incomplete handoff.
        version (Literal[1]): Closed contract version.
    """

    task: str
    identity: str
    hierarchy_digest: str
    workspaces: tuple[Workspace, ...]
    entries: tuple[Entry, ...]
    outcome: Literal["complete", "handoff"] = "complete"
    handoff_reason: str = ""
    version: Literal[1] = 1
