"""
Compile skill evidence without estimating learning from commit volume or repository navigation.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from witful.checkpoints.models import Fact, SkillState
from witful.knowledge.applications import effective_applications, validate_applications
from witful.knowledge.compiler import index, lineage
from witful.knowledge.contracts import as_data
from witful.knowledge.models import Lesson, Skill

if TYPE_CHECKING:
    from collections.abc import Sequence

    from witful.knowledge.models import Application, Identity

__all__ = ["digest", "snapshot"]


def digest(value: object) -> str:
    """
    Fingerprint JSON-compatible content with deterministic key ordering.

    Args:
        value (object): JSON-compatible value.

    Returns:
        str: Full lowercase SHA-256 digest.
    """
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _lesson_digest(lesson: Lesson) -> str:
    """
    Keep checkpoint comparisons stable across the terminology-only hierarchy rename.

    Args:
        lesson (Lesson): Current teaching and its sourced insights.

    Returns:
        str: Digest using the checkpoint contract's original field spelling.
    """
    data = as_data(lesson)

    # Renaming an API field must not count as revised guidance in historical checkpoint comparisons.
    data["lemmas"] = data.pop("insights")
    return digest(data)


def snapshot(identity: Identity, applications: Sequence[Application]) -> tuple[SkillState, ...]:
    """
    Capture active guidance and deduplicated actual use for each skill.

    Args:
        identity (Identity): Validated composed hierarchy.
        applications (Sequence[Application]): Explicit observations, including retained revisions.

    Returns:
        tuple[SkillState, ...]: States sorted by stable ID, with no use inferred for descendant skills.
    """
    validate_applications(identity, applications)
    nodes, parents = index(identity)
    superseded = {item.supersedes for item in nodes.values() if isinstance(item, Lesson) and item.supersedes}
    uses: dict[str, list[Fact]] = {key: [] for key, node in nodes.items() if isinstance(node, Skill)}

    # A task reaching multiple descendants still counts once for their shared skill.
    for event in effective_applications(applications):
        reached = {ancestor for key in event.concept_ids for ancestor in lineage(key, parents)}
        fact = Fact(digest([event.task, event.discipline_id]), digest(as_data(event)))

        for key in reached & uses.keys():
            uses[key].append(fact)

    return tuple(
        SkillState(
            key,
            node.name,
            tuple(sorted((Fact(item.id, _lesson_digest(item)) for item in node.lessons if item.id not in superseded), key=lambda f: f.id)),
            tuple(sorted(uses[key], key=lambda f: f.id)),
        )
        for key, node in sorted(nodes.items())
        if isinstance(node, Skill)
    )
