"""
Enumerate canonical ownership and directed requirements without consulting usage or visual proximity.
"""

from __future__ import annotations

import heapq
from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING

from witful.knowledge.compiler import index, lineage
from witful.knowledge.models import Discipline, Lesson

if TYPE_CHECKING:
    from witful.context.models import Decision, Limits
    from witful.knowledge.compiler import Concept
    from witful.knowledge.models import Identity


def validate(identity: Identity) -> tuple[dict[str, Concept], dict[str, str], set[str]]:
    """
    Recheck pure compiler inputs and identify explicitly superseded subtrees.

    Args:
        identity (Identity): Compiled authorized collection.

    Returns:
        tuple[dict[str, Concept], dict[str, str], set[str]]: Nodes, ownership, and historical IDs.

    Raises:
        ValueError: Metadata, supersession, edges, or directed requirements are invalid.
    """
    nodes, parents = index(identity)
    superseded = {node.supersedes for node in nodes.values() if isinstance(node, Lesson) and node.supersedes}
    if any(identifier not in nodes or not isinstance(nodes[identifier], Lesson) for identifier in superseded):
        raise ValueError("Invalid supersession")
    supersessions: TopologicalSorter[str] = TopologicalSorter()
    for node in nodes.values():
        if isinstance(node, Lesson) and node.supersedes:
            supersessions.add(node.id, node.supersedes)
    try:
        tuple(supersessions.static_order())
    except CycleError as error:
        raise ValueError("Cyclic supersession") from error
    historical = {identifier for identifier in nodes if set(lineage(identifier, parents)) & superseded}
    seen: set[tuple[str, str, str]] = set()
    dependencies: TopologicalSorter[str] = TopologicalSorter()
    for edge in identity.relations:
        key = (edge.source, edge.target, edge.kind)
        if edge.source not in nodes or edge.target not in nodes or edge.source == edge.target or key in seen or not edge.evidence.strip():
            raise ValueError("Invalid relation")
        if edge.kind not in {"requires", "related", "transfers"}:
            raise ValueError("Unknown relation kind")
        seen.add(key)
        if edge.kind == "requires":
            dependencies.add(edge.source, edge.target)
    try:
        tuple(dependencies.static_order())
    except CycleError as error:
        raise ValueError("Cyclic requirements") from error
    return nodes, parents, historical


def enumerate_context(
    identity: Identity,
    seeds: set[str],
    decisions: dict[str, Decision],
    limits: Limits,
) -> tuple[dict[str, set[str]], set[str], set[str], set[str]]:
    """
    Expand reviewed neighborhoods and requirements to a bounded fixed point.

    Args:
        identity (Identity): Validated authorized graph.
        seeds (set[str]): Additive selected and global concepts.
        decisions (dict[str, Decision]): Explicit per-node applicability judgments.
        limits (Limits): Candidate and optional traversal bounds.

    Returns:
        tuple[dict[str, set[str]], set[str], set[str], set[str]]: Paths, mandatory IDs, core review IDs, and omitted candidates.
    """
    nodes, parents, historical = validate(identity)
    children: dict[str, list[str]] = {identifier: [] for identifier in nodes}
    for child, parent in parents.items():
        children[parent].append(child)
    paths: dict[str, set[str]] = {}
    required: set[str] = set()
    core: set[str] = set()
    omitted: set[str] = set()

    def include(identifier: str, reason: str, mandatory: bool, primary: bool) -> None:
        """
        Include a candidate and its ownership metadata without expanding unrelated root descendants.

        Args:
            identifier (str): Existing target concept.
            reason (str): Typed traversal evidence.
            mandatory (bool): Target cannot be excluded.
            primary (bool): Candidate requires review rather than optional deferral.

        Returns:
            None: Local enumeration state is updated without mutating caller input.
        """
        for target in reversed(lineage(identifier, parents)):
            if target not in paths and len(paths) >= limits.nodes:
                omitted.add(target)
                continue
            paths.setdefault(target, set()).add(reason if target == identifier else f"ancestor:{identifier}")
            if mandatory:
                required.add(target)
            if primary:
                core.add(target)

    def expand(identifier: str, reason: str, mandatory: bool, primary: bool) -> None:
        """
        Enumerate all descendant teachings for independent review, including historical records.

        Args:
            identifier (str): Selected root.
            reason (str): Typed inclusion path.
            mandatory (bool): Whether the root itself is mandatory.
            primary (bool): Whether its descendants may be deferred as supplemental material.

        Returns:
            None: Each owned candidate receives an independent review slot.
        """
        include(identifier, reason, mandatory, primary)
        pending = list(children[identifier])
        while pending:
            child = pending.pop()
            include(child, f"owned:{identifier}", False, primary)
            pending.extend(children[child])

    for seed in sorted(seeds):
        expand(seed, "selected", True, True)
        # A mapped Lesson/Insight still exposes the sibling Skills of its owning Discipline.
        owners = lineage(seed, parents)
        discipline = next((nodes[value] for value in owners if isinstance(nodes[value], Discipline)), None)
        if discipline is not None:
            assert isinstance(discipline, Discipline)
            for skill in sorted(discipline.skills, key=lambda item: item.id):
                expand(skill.id, f"neighbor:{discipline.id}", False, True)

    optional_origins = set(seeds)
    processed: set[tuple[str, str, str]] = set()
    while True:
        before = (len(paths), len(required), len(optional_origins))
        active = {
            identifier
            for identifier in paths
            if identifier not in historical
            and (identifier in required or (identifier in decisions and decisions[identifier].status == "applicable"))
        }
        for edge in sorted(identity.relations, key=lambda item: (item.source, item.target, item.kind)):
            key = (edge.source, edge.target, edge.kind)
            if key in processed:
                continue
            if edge.kind == "requires" and edge.source in active:
                expand(edge.target, f"requires:{edge.source}", True, True)
                optional_origins.add(edge.target)
                processed.add(key)
            elif edge.kind != "requires" and limits.optional_hops:
                if edge.source in optional_origins - historical:
                    expand(edge.target, f"{edge.kind}:out:{edge.source}", False, False)
                    processed.add(key)
                elif edge.target in optional_origins - historical:
                    expand(edge.source, f"{edge.kind}:in:{edge.target}", False, False)
                    processed.add(key)
        if before == (len(paths), len(required), len(optional_origins)):
            break
    return paths, required, core, omitted


def ordered(identity: Identity, selected: set[str]) -> tuple[str, ...]:
    """
    Order candidates prerequisite-first with canonical-ID tie breaks.

    Args:
        identity (Identity): Validated graph.
        selected (set[str]): Candidate IDs to order.

    Returns:
        tuple[str, ...]: Stable topological order; incoming requirements are never reversed.
    """
    dependencies = {identifier: set[str]() for identifier in selected}
    followers = {identifier: set[str]() for identifier in selected}
    for edge in identity.relations:
        if edge.kind == "requires" and edge.source in selected and edge.target in selected:
            dependencies[edge.source].add(edge.target)
            followers[edge.target].add(edge.source)
    ready = [identifier for identifier in selected if not dependencies[identifier]]
    heapq.heapify(ready)
    result: list[str] = []
    while ready:
        identifier = heapq.heappop(ready)
        result.append(identifier)
        for follower in sorted(followers[identifier]):
            dependencies[follower].remove(identifier)
            if not dependencies[follower]:
                heapq.heappush(ready, follower)
    return tuple(result)
