"""
Traverse every concept and validate explicit, current review coverage as pure transformations.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from witful.completion.models import Audit, Entry
from witful.knowledge.compiler import index, lineage
from witful.knowledge.contracts import as_data
from witful.knowledge.models import Insight, Lesson

if TYPE_CHECKING:
    from witful.completion.models import Workspace
    from witful.knowledge.models import Identity


def plan(identity: Identity, task: str, workspaces: tuple[Workspace, ...]) -> Audit:
    """
    Enumerate the whole tree without inheriting applicability or certifying any active node.

    Args:
        identity (Identity): Validated compiled hierarchy with original teaching provenance.
        task (str): Explicit nonempty task binding.
        workspaces (tuple[Workspace, ...]): Fresh snapshots resolved at the orchestration boundary.

    Returns:
        Audit: Deterministic pending review; superseded teachings remain visible as history.

    Raises:
        ValueError: The task is empty or workspace paths are empty or duplicated.
    """
    if not task.strip() or any(not item.path.strip() for item in workspaces):
        raise ValueError("A task and nonempty workspace paths are required")
    if len({item.path for item in workspaces}) != len(workspaces):
        raise ValueError("Workspace paths must be unique")
    nodes, parents = index(identity)
    superseded = {node.supersedes: node.id for node in nodes.values() if isinstance(node, Lesson) and node.supersedes}
    entries: list[Entry] = []

    # History is retained at every level; supersession exempts only the old lesson and its owned insights.
    for identifier, node in nodes.items():
        previous = next((ancestor for ancestor in lineage(identifier, parents) if ancestor in superseded), None)
        entries.append(
            Entry(
                identifier,
                parents.get(identifier),
                type(node).__name__,
                node.name,
                node.statement if isinstance(node, (Lesson, Insight)) else "",
                node.source if isinstance(node, (Lesson, Insight)) else "",
                "historical" if previous is not None else "pending",
                f"Superseded by {superseded[previous]}" if previous is not None else "",
            )
        )
    digest = hashlib.sha256(json.dumps(as_data(identity), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return Audit(task, identity.id, digest, tuple(sorted(workspaces, key=lambda item: item.path)), tuple(entries))


def check(audit: Audit, identity: Identity, task: str, workspaces: tuple[Workspace, ...]) -> tuple[str, ...]:
    """
    Reject gaps, stale bindings, ambiguous entries, and unsupported completion claims.

    Args:
        audit (Audit): Caller-authored review, validated against its closed source schema.
        identity (Identity): Current compiled hierarchy.
        task (str): Independently selected expected task binding.
        workspaces (tuple[Workspace, ...]): Independently refreshed expected workspaces.

    Returns:
        tuple[str, ...]: Deterministically ordered diagnostics; empty means coverage passed.
    """
    expected = plan(identity, task, workspaces)
    errors: list[str] = []
    if (audit.task, audit.identity, audit.hierarchy_digest) != (expected.task, expected.identity, expected.hierarchy_digest):
        errors.append("Task, identity, or hierarchy changed; generate and review a fresh plan")
    if audit.workspaces != expected.workspaces:
        errors.append("Workspace selection or contents changed; generate and review a fresh plan")
    identifiers = [item.id for item in audit.entries]
    wanted = {item.id: item for item in expected.entries}
    if len(set(identifiers)) != len(identifiers):
        errors.append("Duplicate review entries")
    missing = wanted.keys() - set(identifiers)
    unknown = set(identifiers) - wanted.keys()
    if missing:
        errors.append("Missing concepts: " + ", ".join(sorted(missing)))
    if unknown:
        errors.append("Unknown concepts: " + ", ".join(sorted(unknown)))
    reviewed = {item.id: item for item in audit.entries}
    parents = {item.id: item.parent for item in expected.entries if item.parent is not None}

    # A parent checkbox never discharges its children. Every active node needs an independent disposition.
    for entry in audit.entries:
        reference = wanted.get(entry.id)
        if reference is None:
            continue
        metadata = (entry.parent, entry.kind, entry.name, entry.statement, entry.source)
        if metadata != (reference.parent, reference.kind, reference.name, reference.statement, reference.source):
            errors.append(f"{entry.id}: hierarchy metadata was changed")
        if reference.status == "historical":
            if entry != reference:
                errors.append(f"{entry.id}: preserve the generated supersession record")
            continue
        if entry.status in {"pending", "historical"}:
            errors.append(f"{entry.id}: active concept has not been reviewed")
        if not entry.reason.strip():
            errors.append(f"{entry.id}: a reviewed reason is required")
        if entry.status == "satisfied" and (not entry.evidence or any(not value.strip() for value in entry.evidence)):
            errors.append(f"{entry.id}: satisfied entries require nonempty evidence references")
        if entry.status == "blocked":
            if not entry.next_action.strip():
                errors.append(f"{entry.id}: blocked entries require a concrete next action")
            if audit.outcome != "handoff":
                errors.append(f"{entry.id}: blocked work cannot be declared complete")
        if entry.status in {"satisfied", "blocked"}:
            for ancestor in lineage(entry.id, parents)[1:]:
                owner = reviewed.get(ancestor)
                if owner is not None and owner.status == "not_applicable":
                    errors.append(f"{entry.id}: applicable child conflicts with excluded ancestor {ancestor}")
    if audit.outcome == "handoff" and not audit.handoff_reason.strip():
        errors.append("An incomplete handoff requires an explicit reason")
    return tuple(errors)
