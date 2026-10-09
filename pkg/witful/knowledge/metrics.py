"""
Measure recorded applications and cross-discipline reuse without estimating competence.
"""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations
from typing import TYPE_CHECKING

from attrs import frozen

from witful.knowledge.applications import effective_applications, validate_applications
from witful.knowledge.compiler import index, lineage
from witful.knowledge.models import Discipline, Skill

if TYPE_CHECKING:
    from collections.abc import Sequence

    from witful.knowledge.models import Application, Identity

__all__ = ["Edge", "Usage", "affinity", "graph_edges", "usage"]


@frozen
class Usage:
    """
    Count distinct current task/context observations reaching a concept or its descendants.

    Attributes:
        applications (int): Recorded uses, regardless of reported outcome.
        verified (int): Uses explicitly reported as verified, not independently certified success.
        unsuccessful (int): Uses explicitly reported as unsuccessful.
        contexts (tuple[str, ...]): Distinct application disciplines.
    """

    applications: int = 0
    verified: int = 0
    unsuccessful: int = 0
    contexts: tuple[str, ...] = ()


@frozen
class Edge:
    """
    Preserve relationship type and evidence separately from display/layout weight.

    Attributes:
        source (str): Origin concept ID.
        target (str): Destination concept ID.
        kind (str): Contains, curated relationship, co-use, or observed transfer.
        applications (int): Current task/context observations supporting this link.
        verified (int): Observations reported as verified.
        strength (float): Normalized observed affinity, zero for organizational or proposed links.
        evidence (str): Explicit rationale for curated links; empty for computed links.
    """

    source: str
    target: str
    kind: str
    applications: int = 0
    verified: int = 0
    strength: float = 0.0
    evidence: str = ""


def affinity(joint: int, left: int, right: int) -> float:
    """
    Normalize verified co-use by each concept's verified application count.

    Args:
        joint (int): Verified task/context observations using both concepts.
        left (int): Verified observations using the first concept.
        right (int): Verified observations using the second concept.

    Returns:
        float: Cosine similarity of binary application incidence, in the interval zero through one.

    Raises:
        ValueError: Counts are negative or the joint count exceeds either marginal count.
    """
    if min(joint, left, right) < 0 or joint > min(left, right):
        raise ValueError("Invalid co-application counts")

    return joint / math.sqrt(left * right) if left and right else 0.0


def usage(identity: Identity, applications: Sequence[Application]) -> dict[str, Usage]:
    """
    Roll up explicit uses once per ancestor without claiming that unused descendants were applied.

    Args:
        identity (Identity): Validated hierarchy.
        applications (Sequence[Application]): Application history with explicit outcomes.

    Returns:
        dict[str, Usage]: Counts for every node, including nodes with no recorded applications.
    """
    validate_applications(identity, applications)
    nodes, parents = index(identity)
    observations: dict[str, list[Application]] = defaultdict(list)

    for event in effective_applications(applications):
        reached = {ancestor for concept in event.concept_ids for ancestor in lineage(concept, parents)}

        for identifier in reached:
            observations[identifier].append(event)

    return {
        identifier: Usage(
            len(observations[identifier]),
            sum(event.outcome == "verified" for event in observations[identifier]),
            sum(event.outcome == "unsuccessful" for event in observations[identifier]),
            tuple(sorted({event.discipline_id for event in observations[identifier]})),
        )
        for identifier in sorted(nodes)
    }


def graph_edges(identity: Identity, applications: Sequence[Application]) -> tuple[Edge, ...]:
    """
    Derive direct co-use, skill-level reuse, and cross-discipline transfer from explicit observations.

    Args:
        identity (Identity): Hierarchy plus curated relations.
        applications (Sequence[Application]): Application history.

    Returns:
        tuple[Edge, ...]: Stable typed edges, keeping proposed relationships separate from observed reuse.
    """
    counts = usage(identity, applications)
    nodes, parents = index(identity)
    result = [Edge(parent, child, "contains") for child, parent in sorted(parents.items())]
    result.extend(Edge(link.source, link.target, link.kind, evidence=link.evidence) for link in identity.relations)
    pairs: dict[tuple[str, str], list[Application]] = defaultdict(list)
    transfers: dict[tuple[str, str], list[Application]] = defaultdict(list)

    for event in effective_applications(applications):
        paths = {concept: lineage(concept, parents) for concept in event.concept_ids}
        skills = {ancestor for path in paths.values() for ancestor in path if isinstance(nodes[ancestor], Skill)}

        # Parent/child membership is organizational, not independent evidence of conceptual reuse.
        observed_pairs = set(combinations(sorted(skills), 2))
        observed_pairs.update(
            (left, right) for left, right in combinations(event.concept_ids, 2) if left not in paths[right] and right not in paths[left]
        )

        for pair in sorted(observed_pairs):
            pairs[pair].append(event)

        # A task may use a concept outside its home discipline even when no second skill is explicitly recorded.
        for skill in sorted(skills):
            home = next(ancestor for ancestor in lineage(skill, parents) if isinstance(nodes[ancestor], Discipline))

            if event.discipline_id != home:
                transfers[skill, event.discipline_id].append(event)

    for (left, right), events in sorted(pairs.items()):
        verified = sum(event.outcome == "verified" for event in events)
        result.append(Edge(left, right, "co-use", len(events), verified, affinity(verified, counts[left].verified, counts[right].verified)))

    for (skill, context), events in sorted(transfers.items()):
        verified = sum(event.outcome == "verified" for event in events)
        result.append(
            Edge(
                skill,
                context,
                "observed-transfer",
                len(events),
                verified,
                verified / counts[skill].verified if counts[skill].verified else 0.0,
            )
        )

    return tuple(sorted(result, key=lambda edge: (edge.kind, edge.source, edge.target)))
