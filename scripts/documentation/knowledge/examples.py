"""
Define independent, wholly invented collections for the public knowledge-graph illustrations.
"""

from __future__ import annotations

import hashlib

from attrs import evolve, frozen
from witful.knowledge.applications import application_id, validate_applications
from witful.knowledge.models import Application, Discipline, Identity, Insight, Lesson, Relation, Skill

type Teaching = tuple[str, str, str]
type Area = tuple[str, tuple[Teaching, ...]]

_SOURCE = "Invented documentation example; no personal collection or actual task outcome."
_SYNC: Teaching = ("Synchronize identity", "Refresh before work", "Preserve local edits")
_REVIEW: Teaching = ("Completion review", "Check each requirement", "Coverage needs evidence")
_COLLECTIONS: tuple[tuple[str, str, tuple[Area, ...]], ...] = (
    (
        "application",
        "Application engineer",
        (
            (
                "Software design",
                (
                    ("API contracts", "Keep interfaces explicit", "Reject unknown fields"),
                    ("Testing", "Exercise failure paths", "Keep a regression"),
                ),
            ),
            (
                "Delivery",
                (
                    ("Code review", "Explain the change", "Link validation evidence"),
                    ("Signed releases", "Verify published bytes", "Check the signature"),
                ),
            ),
            (
                "Communication",
                (
                    ("Documentation", "Explain intent", "Name the invariant"),
                    ("Visual evidence", "Show the relationship", "Label what links mean"),
                ),
            ),
            ("Continual learning", (_SYNC, _REVIEW)),
        ),
    ),
    (
        "platform",
        "Platform engineer",
        (
            (
                "Operations",
                (
                    ("Deployment", "Test the rollout", "Check readiness"),
                    ("Observability", "Measure owned queues", "Separate health signals"),
                ),
            ),
            (
                "Security",
                (
                    ("Key custody", "Separate key access", "Verify recipient scope"),
                    ("Access policy", "Use explicit grants", "Test denied requests"),
                ),
            ),
            (
                "Delivery",
                (
                    ("Signed releases", "Verify published bytes", "Check the signature"),
                    ("Recovery", "Rehearse restoration", "Keep recovery evidence"),
                ),
            ),
            ("Continual learning", (_SYNC, ("Incident learning", "Record confirmed causes", "Distinguish hypotheses"))),
        ),
    ),
    (
        "research",
        "Research engineer",
        (
            (
                "Data engineering",
                (
                    ("Data quality", "Validate source data", "Keep missing values visible"),
                    ("Provenance", "Bind outputs to inputs", "Record source revisions"),
                ),
            ),
            (
                "Experiment design",
                (
                    ("Reproducibility", "Fix replay inputs", "Record the random seed"),
                    ("Comparison", "Match comparison scope", "Use the same baseline"),
                ),
            ),
            (
                "Communication",
                (
                    ("Documentation", "Explain the method", "Name the assumptions"),
                    ("Visual evidence", "Show measured results", "Label units and limits"),
                ),
            ),
            ("Continual learning", (_SYNC, ("Experiment review", "Revisit the conclusion", "Retain negative results"))),
        ),
    ),
)


@frozen
class Example:
    """
    Keep each illustration's hierarchy and observation history together.

    Attributes:
        identity (Identity): Independently namespaced synthetic collection.
        applications (tuple[Application, ...]): Invented, unassessed task observations scoped to this collection.
    """

    identity: Identity
    applications: tuple[Application, ...]


def _skill(prefix: str, teaching: Teaching) -> Skill:
    """
    Give a synthetic capability its own sourced lesson and concrete insight.

    Args:
        prefix (str): Collection-local stable skill identifier.
        teaching (Teaching): Skill, lesson and insight labels.

    Returns:
        Skill: Complete subtree whose identifiers cannot alias another example's records.
    """
    skill, lesson, insight = teaching
    return Skill(
        prefix,
        skill,
        (
            Lesson(
                hashlib.sha256(prefix.encode()).hexdigest(),
                lesson,
                lesson + ".",
                _SOURCE,
                "2026-01-01T12:00:00+00:00",
                insights=(Insight(f"{prefix}:insight", insight, insight + ".", _SOURCE),),
            ),
        ),
    )


def examples() -> tuple[Example, ...]:
    """
    Build three complete hierarchies with independent relationships and application histories.

    Returns:
        tuple[Example, ...]: Deterministic illustration inputs, with no collection, clock or credential reads.
    """
    result: list[Example] = []

    for alias, name, areas in _COLLECTIONS:
        disciplines = tuple(
            Discipline(
                f"example:{alias}:area:{ordinal}",
                area,
                tuple(_skill(f"example:{alias}:skill:{ordinal}:{part}", teaching) for part, teaching in enumerate(teachings)),
            )
            for ordinal, (area, teachings) in enumerate(areas)
        )
        # Curated bridges remain inside the owning identity. Similar labels in
        # another collection never imply shared records or a transfer grant.
        first, second, third, learning = disciplines
        identity = Identity(
            f"example:{alias}",
            name,
            disciplines,
            (
                Relation(first.skills[0].id, first.skills[1].id, "related", "Synthetic bridge: complementary practice."),
                Relation(second.skills[0].id, third.skills[0].id, "requires", "Synthetic prerequisite for this collection."),
                Relation(learning.skills[1].id, first.skills[1].id, "transfers", "Synthetic proposal to reuse the review practice."),
            ),
        )
        applications: list[Application] = []

        # Fixed task dates supply activity for the emphasis map. Unassessed
        # outcomes cannot manufacture successful reuse or a real productivity claim.
        for ordinal, discipline in enumerate(disciplines):
            for part, skill in enumerate(discipline.skills):
                companion = disciplines[(ordinal + 1) % len(disciplines)].skills[part]
                event = Application(
                    "",
                    f"example:{alias}:task:{ordinal}:{part}",
                    discipline.id,
                    tuple(sorted((skill.lessons[0].insights[0].id, companion.id))),
                    "unassessed",
                    _SOURCE,
                    f"2026-01-{30 - ordinal * 7 - part:02d}T12:00:00+00:00",
                )
                applications.append(evolve(event, id=application_id(event)))

        validate_applications(identity, applications)
        result.append(Example(identity, tuple(applications)))

    return tuple(result)
