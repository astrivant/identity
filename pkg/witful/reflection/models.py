"""
Define evidence-backed retrospective assessments and configurable review cadence.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen

from witful.life.models import Snapshot  # noqa: TC001 - runtime schema generation

__all__ = ["Assessment", "Config", "Review"]


@frozen
class Config:
    """
    Bound periodic review work without generating judgments automatically.

    Attributes:
        enabled (bool): Generate review plans and figures during collection refresh.
        interval_commits (int): First-parent commits between completed review rounds.
        batch_size (int): Maximum decisions requested in one round, oldest review first.
    """

    enabled: bool = True
    interval_commits: int = 100
    batch_size: int = 20


@frozen
class Assessment:
    """
    Compare a past choice with current knowledge under its original recorded constraints.

    Attributes:
        decision_id (str): Immutable Life event whose choice and context remain unchanged.
        current_choice (str): Choice the reviewer would make now under that original context.
        rationale (str): Concise explanation, including uncertainties and constraints.
        knowledge_ids (tuple[str, ...]): Concepts supporting the assessment in the review snapshot.
        current_support (int | None): Present support for the original choice, from -2 to 2; null means unknown.
        observed_outcome (int | None): Reported outcome, from -2 to 2; never a hypothetical alternative's outcome.
        outcome_evidence (str): Source for an observed outcome; required when it is scored.
        context_change (str): What changed after the decision, or an explicit statement that this is unknown.
        context_effect (int | None): Reported change in circumstances, from -2 to 2; not proof of causation.
        context_evidence (str): Source for a scored change in circumstances.
        proposed_lessons (tuple[str, ...]): Pending teachings for human review, never automatically accepted.
        seek_help (bool): Whether the reviewer recommends asking a person or another agent for assistance.
    """

    decision_id: str
    current_choice: str
    rationale: str
    knowledge_ids: tuple[str, ...]
    current_support: int | None = None
    observed_outcome: int | None = None
    outcome_evidence: str = ""
    context_change: str = "Unknown"
    context_effect: int | None = None
    context_evidence: str = ""
    proposed_lessons: tuple[str, ...] = ()
    seek_help: bool = False


@frozen
class Review:
    """
    Retain an immutable review round and the exact knowledge state used by its reviewer.

    Attributes:
        id (str): Content hash excluding this field.
        previous (str | None): Preceding review's identifier.
        recorded_at (str): UTC observation time, not a reconstructed decision date.
        revision (str): Git cadence anchor; source bytes are captured independently in snapshot.
        snapshot (Snapshot): Exact reviewed knowledge, including any working-tree edits.
        assessments (tuple[Assessment, ...]): Complete requested batch, sorted by decision identifier.
        version (Literal[1]): Supported journal format.
    """

    id: str
    previous: str | None
    recorded_at: str
    revision: str
    snapshot: Snapshot
    assessments: tuple[Assessment, ...]
    version: Literal[1] = 1
