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
type Scenario = tuple[str, str, tuple[str, ...]]

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
_REUSE: dict[str, tuple[Scenario, ...]] = {
    "application": (
        ("review-api-change", "Delivery", ("API contracts", "Testing", "Code review", "Documentation")),
        ("release-api-change", "Delivery", ("Testing", "Signed releases", "Code review", "Documentation")),
        ("document-contract", "Communication", ("API contracts", "Documentation", "Visual evidence")),
        ("review-follow-up", "Continual learning", ("Completion review", "Testing", "Code review")),
    ),
    "platform": (
        ("rollout-service", "Operations", ("Deployment", "Observability", "Access policy")),
        ("release-rollout", "Delivery", ("Signed releases", "Key custody", "Deployment")),
        ("rehearse-recovery", "Delivery", ("Recovery", "Observability", "Key custody")),
        ("review-incident", "Continual learning", ("Incident learning", "Observability", "Deployment")),
    ),
    "research": (
        ("publish-study", "Communication", ("Data quality", "Provenance", "Reproducibility", "Visual evidence")),
        ("compare-revisions", "Experiment design", ("Comparison", "Data quality", "Provenance", "Visual evidence")),
        ("replay-result", "Experiment design", ("Reproducibility", "Provenance", "Documentation")),
        ("review-experiment", "Continual learning", ("Experiment review", "Comparison", "Visual evidence")),
    ),
}
_PREREQUISITES: dict[str, tuple[str, str, str]] = {
    "application": ("Signed releases", "Code review", "Review the change before publishing it."),
    "platform": ("Signed releases", "Key custody", "Controlled signing keys are needed to verify a release."),
    "research": ("Visual evidence", "Data quality", "Validate plotted measurements before drawing a conclusion."),
}


@frozen
class Example:
    """
    Keep each illustration's hierarchy and observation history together.

    Attributes:
        identity (Identity): Independently namespaced synthetic collection.
        applications (tuple[Application, ...]): Invented task observations and outcomes scoped to this collection.
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
        first, _, _, learning = disciplines
        skills = {skill.name: skill.id for discipline in disciplines for skill in discipline.skills}
        contexts = {discipline.name: discipline.id for discipline in disciplines}
        source, target, rationale = _PREREQUISITES[alias]
        identity = Identity(
            f"example:{alias}",
            name,
            disciplines,
            (
                Relation(first.skills[0].id, first.skills[1].id, "related", "Synthetic bridge: complementary practice."),
                Relation(skills[source], skills[target], "requires", "Synthetic prerequisite: " + rationale),
                Relation(learning.skills[1].id, first.skills[1].id, "transfers", "Synthetic proposal to reuse the review practice."),
            ),
        )
        applications: list[Application] = []

        # Early observations show activity without reporting an outcome. The
        # explicit scenarios below then demonstrate verified, repeated reuse.
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

        # These successful outcomes are invented demo inputs, not measurements.
        # Repeat skills across named scenarios so relative co-use has real graph
        # structure instead of assigning a decorative weight to an edge.
        for ordinal, (task, context, names) in enumerate(_REUSE[alias]):
            event = Application(
                "",
                f"example:{alias}:{task}",
                contexts[context],
                tuple(sorted(skills[name] for name in names)),
                "verified",
                "Invented successful scenario for the reuse demonstration. " + _SOURCE,
                f"2026-02-{ordinal + 2:02d}T12:00:00+00:00",
            )
            applications.append(evolve(event, id=application_id(event)))

        validate_applications(identity, applications)
        result.append(Example(identity, tuple(applications)))

    return tuple(result)
