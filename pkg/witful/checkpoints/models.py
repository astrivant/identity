"""
Define portable checkpoint snapshots independently of Git paths and storage engines.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen

__all__ = ["Checkpoint", "Fact", "SkillState"]


@frozen
class Fact:
    """
    Identify a documented item and its revision without copying its text into every checkpoint.

    Attributes:
        id (str): Stable item key; application keys hash their task and context.
        digest (str): SHA-256 of the corresponding canonical source object.
    """

    id: str
    digest: str


@frozen
class SkillState:
    """
    Snapshot one skill's current teachings and explicitly recorded applications.

    Attributes:
        id (str): Stable skill ID.
        name (str): Reviewed display name at this boundary.
        lessons (tuple[Fact, ...]): Active lessons, including their insight annotations in the digest.
        uses (tuple[Fact, ...]): Latest observation for each task/context reaching this skill.
    """

    id: str
    name: str
    lessons: tuple[Fact, ...] = ()
    uses: tuple[Fact, ...] = ()


@frozen
class Checkpoint:
    """
    Mark a project visit or commit without asserting that the project caused the observed changes.

    Attributes:
        id (str): SHA-256 of the complete record except this field.
        previous (str | None): Prior checkpoint ID, giving an explicit chronology.
        project (str): User-selected stable public or private alias, never an inferred remote URL.
        revision (str): Exact Git commit at recording time.
        recorded_at (str): Timezone-aware recording time, independent of Git author dates.
        skills (tuple[SkillState, ...]): Complete canonical state, sufficient to recompute comparisons.
        version (Literal[1]): Supported source schema version.
    """

    id: str
    previous: str | None
    project: str
    revision: str
    recorded_at: str
    skills: tuple[SkillState, ...] = ()
    version: Literal[1] = 1
