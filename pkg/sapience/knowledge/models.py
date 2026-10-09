"""
Define immutable source contracts and the composed hierarchy of understanding.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen

__all__ = [
    "Annotation",
    "Application",
    "Catalog",
    "Discipline",
    "DisciplineSpec",
    "Identity",
    "Lemma",
    "Lesson",
    "Relation",
    "Skill",
    "SkillSpec",
]


@frozen
class Lemma:
    """
    Express one reusable, scoped sub-lesson without implying mathematical proof.

    Attributes:
        id (str): Stable concept identifier.
        name (str): Short display label.
        statement (str): Independently useful guidance.
        source (str): Evidence or teaching reference supporting this decomposition.
    """

    id: str
    name: str
    statement: str
    source: str


@frozen
class Lesson:
    """
    Preserve an authoritative journal observation inside the composed model.

    Attributes:
        id (str): Original content-derived journal identifier.
        name (str): Short label from the catalog, or the journal's subject.
        statement (str): Original teaching, unchanged by classification.
        source (str): Original provenance.
        observed_at (str): Original recording time.
        supersedes (str | None): Explicit earlier record corrected by this teaching.
        lemmas (tuple[Lemma, ...]): Optional, explicitly sourced sub-lessons.
    """

    id: str
    name: str
    statement: str
    source: str
    observed_at: str
    supersedes: str | None = None
    lemmas: tuple[Lemma, ...] = ()


@frozen
class Skill:
    """
    Group related teachings under one reusable engineering capability.

    Attributes:
        id (str): Stable skill identifier.
        name (str): Human-readable capability.
        lessons (tuple[Lesson, ...]): Canonical ownership of journal records.
    """

    id: str
    name: str
    lessons: tuple[Lesson, ...] = ()


@frozen
class Discipline:
    """
    Group capabilities while allowing reuse edges across the organizational boundary.

    Attributes:
        id (str): Stable discipline identifier.
        name (str): Human-readable area of practice.
        skills (tuple[Skill, ...]): Canonical skill owners, not limits on application contexts.
    """

    id: str
    name: str
    skills: tuple[Skill, ...] = ()


@frozen
class Relation:
    """
    Record a directed, explicitly described relationship independently of observed usage.

    Attributes:
        source (str): Existing origin concept ID.
        target (str): Existing destination concept ID.
        kind (Literal["related", "requires", "transfers"]): Reusable relationship semantics.
        evidence (str): Rationale or source; a proposed bridge is not an observed success.
    """

    source: str
    target: str
    kind: Literal["related", "requires", "transfers"]
    evidence: str


@frozen
class Identity:
    """
    Own the complete hierarchy and sourced cross-cutting relationships.

    Attributes:
        id (str): Stable root identifier.
        name (str): Display name for the curated knowledge collection.
        disciplines (tuple[Discipline, ...]): Organizational hierarchy.
        relations (tuple[Relation, ...]): Reuse graph, separate from containment.
    """

    id: str
    name: str
    disciplines: tuple[Discipline, ...] = ()
    relations: tuple[Relation, ...] = ()


@frozen
class SkillSpec:
    """
    Assign existing journal topics to an explicitly curated capability.

    Attributes:
        id (str): Stable skill identifier.
        name (str): Display label.
        topics (tuple[str, ...]): Exact journal subjects owned by this skill.
    """

    id: str
    name: str
    topics: tuple[str, ...] = ()


@frozen
class DisciplineSpec:
    """
    Declare the skill groups for one organizational discipline.

    Attributes:
        id (str): Stable discipline identifier.
        name (str): Display label.
        skills (tuple[SkillSpec, ...]): Source declarations for compilation.
    """

    id: str
    name: str
    skills: tuple[SkillSpec, ...] = ()


@frozen
class Annotation:
    """
    Enrich a journal record without rewriting its historical source.

    Attributes:
        lesson_id (str): Existing full journal ID.
        name (str): Concise label, without changing the lesson statement.
        lemmas (tuple[Lemma, ...]): Explicitly authored sub-lessons.
    """

    lesson_id: str
    name: str
    lemmas: tuple[Lemma, ...] = ()


@frozen
class Catalog:
    """
    Describe reviewed classifications and reuse relationships for a journal.

    Attributes:
        id (str): Stable identity ID.
        name (str): Collection label.
        version (Literal[1]): Supported source format.
        disciplines (tuple[DisciplineSpec, ...]): Explicit topic assignments.
        annotations (tuple[Annotation, ...]): Optional named decompositions.
        relations (tuple[Relation, ...]): Explicit relationships between compiled concepts.
    """

    id: str
    name: str
    version: Literal[1] = 1
    disciplines: tuple[DisciplineSpec, ...] = ()
    annotations: tuple[Annotation, ...] = ()
    relations: tuple[Relation, ...] = ()


@frozen
class Application:
    """
    Record a deliberate application to one task, not a model's hidden internal activity.

    Attributes:
        id (str): Content-derived ID for idempotent recording.
        task (str): Stable local task reference, without private prompt bodies.
        discipline_id (str): Actual application context, potentially outside a concept's home discipline.
        concept_ids (tuple[str, ...]): Concepts explicitly used together in this observation.
        outcome (Literal["unassessed", "verified", "unsuccessful"]): Reported outcome of applying these concepts.
        evidence (str): Concise source or validation reference supporting the reported outcome.
        observed_at (str): Time this application was recorded, not an inferred teaching date.
    """

    id: str
    task: str
    discipline_id: str
    concept_ids: tuple[str, ...]
    outcome: Literal["unassessed", "verified", "unsuccessful"]
    evidence: str
    observed_at: str
