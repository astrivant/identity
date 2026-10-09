"""
Compile the unchanged lesson archive and curated classifications into one hierarchy.
"""

from __future__ import annotations

import hashlib
from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING

from sapience.knowledge.models import Catalog, Discipline, Identity, Lemma, Lesson, Skill

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sapience.lessons import Lesson as JournalLesson

__all__ = ["Concept", "compile_identity", "index", "lineage"]

type Concept = Identity | Discipline | Skill | Lesson | Lemma


def _children(node: Concept) -> tuple[Concept, ...]:
    """
    Traverse ownership without following cross-cutting reuse relationships.

    Args:
        node (Concept): One hierarchy node.

    Returns:
        tuple[Concept, ...]: Directly owned children, empty for lemmas.
    """
    if isinstance(node, Identity):
        return node.disciplines
    if isinstance(node, Discipline):
        return node.skills
    if isinstance(node, Skill):
        return node.lessons
    if isinstance(node, Lesson):
        return node.lemmas
    return ()


def index(identity: Identity) -> tuple[dict[str, Concept], dict[str, str]]:
    """
    Validate unique ownership and build concept and parent lookup tables.

    Args:
        identity (Identity): Compiled hierarchy.

    Returns:
        tuple[dict[str, Concept], dict[str, str]]: Concepts by ID and child-to-parent relationships.

    Raises:
        ValueError: Identifiers or labels are empty, reserved, or duplicated.
    """
    nodes: dict[str, Concept] = {}
    parents: dict[str, str] = {}
    pending: list[tuple[Concept, str | None]] = [(identity, None)]

    while pending:
        node, parent = pending.pop()

        if not node.id.strip() or not node.name.strip() or node.id in nodes:
            raise ValueError(f"Empty or duplicated concept: {node.id}")
        if isinstance(node, (Lesson, Lemma)) and (not node.statement.strip() or not node.source.strip()):
            raise ValueError("Teachings require a statement and explicit provenance")

        nodes[node.id] = node

        if parent is not None:
            parents[node.id] = parent

        pending.extend((child, node.id) for child in reversed(_children(node)))

    return nodes, parents


def lineage(identifier: str, parents: dict[str, str]) -> tuple[str, ...]:
    """
    Resolve a concept and its ancestors for deduplicated upward usage accounting.

    Args:
        identifier (str): Existing concept identifier.
        parents (dict[str, str]): Validated acyclic ownership map.

    Returns:
        tuple[str, ...]: IDs from the specified node through the identity root.
    """
    result = [identifier]

    while result[-1] in parents:
        result.append(parents[result[-1]])

    return tuple(result)


def compile_identity(records: Sequence[JournalLesson], catalog: Catalog) -> Identity:
    """
    Preserve every journal record once and reject ambiguous classifications or reuse edges.

    Args:
        records (Sequence[JournalLesson]): Previously validated append-only journal records.
        catalog (Catalog): Reviewed organizational assignments and annotations.

    Returns:
        Identity: Deterministic composed model, including an explicit group for unclassified new topics.

    Raises:
        ValueError: Topics have multiple owners, annotations or edges dangle, or requirements contain a cycle.
    """
    annotations = {item.lesson_id: item for item in catalog.annotations}

    if len(annotations) != len(catalog.annotations) or annotations.keys() - {record.id for record in records}:
        raise ValueError("Annotations must identify unique existing journal records")

    topics: dict[str, str] = {}
    disciplines: list[Discipline] = []

    # Classification never rewrites a teaching, its timestamp, or its supersession reference.
    def lesson(record: JournalLesson) -> Lesson:
        """
        Attach optional annotations to an unchanged archive observation.

        Args:
            record (JournalLesson): Validated source record.

        Returns:
            Lesson: Typed observation and explicit decomposition.
        """
        annotation = annotations.get(record.id)
        return Lesson(
            record.id,
            annotation.name if annotation else record.topic,
            record.lesson,
            record.source,
            record.observed_at,
            record.supersedes,
            annotation.lemmas if annotation else (),
        )

    for discipline in catalog.disciplines:
        skills: list[Skill] = []

        for skill in discipline.skills:
            for topic in skill.topics:
                if topic in topics:
                    raise ValueError(f"Topic has multiple owners: {topic}")

                topics[topic] = skill.id

            skills.append(
                Skill(skill.id, skill.name, tuple(lesson(r) for r in sorted(records, key=lambda r: r.id) if r.topic in skill.topics))
            )

        disciplines.append(Discipline(discipline.id, discipline.name, tuple(skills)))

    # New teaching topics remain visible without assigning a discipline based on guessed semantic similarity.
    unknown = sorted({record.topic for record in records} - topics.keys())

    if unknown:
        disciplines.append(
            Discipline(
                "discipline:unclassified",
                "Unclassified",
                tuple(
                    Skill(
                        f"skill:unclassified:{hashlib.sha256(topic.encode()).hexdigest()[:16]}",
                        topic,
                        tuple(lesson(record) for record in sorted(records, key=lambda r: r.id) if record.topic == topic),
                    )
                    for topic in unknown
                ),
            )
        )

    result = Identity(catalog.id, catalog.name, tuple(disciplines), catalog.relations)
    nodes, _ = index(result)
    requirements: TopologicalSorter[str] = TopologicalSorter()
    seen: set[tuple[str, str, str]] = set()

    for relation in catalog.relations:
        key = (relation.source, relation.target, relation.kind)

        if relation.source not in nodes or relation.target not in nodes or relation.source == relation.target:
            raise ValueError("A relation has a missing endpoint or a self-reference")
        if key in seen or not relation.evidence.strip():
            raise ValueError("Relations require unique endpoints/kinds and explicit evidence")

        seen.add(key)

        if relation.kind == "requires":
            requirements.add(relation.source, relation.target)

    try:
        tuple(requirements.static_order())
    except CycleError as error:
        raise ValueError("Prerequisite relationships must be acyclic") from error

    return result
