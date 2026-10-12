"""
Compare checkpoint evidence using stable IDs rather than subtracting aggregate counts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import frozen

from witful.checkpoints.models import SkillState

if TYPE_CHECKING:
    from collections.abc import Sequence

    from witful.checkpoints.models import Checkpoint, Fact

__all__ = ["Change", "SkillDiff", "compare", "compare_states", "visits"]


@frozen
class Change:
    """
    Distinguish new evidence from revisions and withdrawals.

    Attributes:
        added (tuple[str, ...]): Keys present only in the later snapshot.
        removed (tuple[str, ...]): Keys present only in the earlier snapshot.
        revised (tuple[str, ...]): Shared keys with changed content fingerprints.
    """

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    revised: tuple[str, ...] = ()


@frozen
class SkillDiff:
    """
    Describe one changed skill without interpreting its counts as competence.

    Attributes:
        id (str): Stable skill ID.
        name (str): Most recent label, or the earlier one for a removed skill.
        status (str): Added, removed, renamed, or retained skill.
        lessons (Change): Documented teaching changes; classification changes remain observable.
        uses (Change): Actual task/context observations added, removed, or revised.
    """

    id: str
    name: str
    status: str
    lessons: Change
    uses: Change


def _change(before: tuple[Fact, ...], after: tuple[Fact, ...]) -> Change:
    """
    Derive exact set differences and shared-key revisions.

    Args:
        before (tuple[Fact, ...]): Earlier validated facts.
        after (tuple[Fact, ...]): Later validated facts.

    Returns:
        Change: Canonical keys grouped by their observed change type.
    """
    left = {fact.id: fact.digest for fact in before}
    right = {fact.id: fact.digest for fact in after}
    return Change(
        tuple(sorted(right.keys() - left.keys())),
        tuple(sorted(left.keys() - right.keys())),
        tuple(sorted(key for key in left.keys() & right.keys() if left[key] != right[key])),
    )


def compare(before: Checkpoint, after: Checkpoint) -> tuple[SkillDiff, ...]:
    """
    Compare any two stored snapshots without loading current lessons or application records.

    Args:
        before (Checkpoint): Earlier or explicitly chosen baseline.
        after (Checkpoint): Comparison target.

    Returns:
        tuple[SkillDiff, ...]: Only changed skills, sorted by stable ID; identical evidence yields no differences.
    """
    return compare_states(before.skills, after.skills)


def compare_states(before: tuple[SkillState, ...], after: tuple[SkillState, ...]) -> tuple[SkillDiff, ...]:
    """
    Compare native skill snapshots independently of the boundary that retained them.

    Args:
        before (tuple[SkillState, ...]): Earlier native skill evidence.
        after (tuple[SkillState, ...]): Later native skill evidence.

    Returns:
        tuple[SkillDiff, ...]: Exact recorded additions, removals, revisions, and classification changes.
    """
    left = {state.id: state for state in before}
    right = {state.id: state for state in after}
    result: list[SkillDiff] = []

    for key in sorted(left.keys() | right.keys()):
        prior = left.get(key, SkillState(key, right[key].name)) if key not in left else left[key]
        current = right.get(key, SkillState(key, prior.name))
        status = "added" if key not in left else "removed" if key not in right else "renamed" if prior.name != current.name else "retained"
        item = SkillDiff(key, current.name, status, _change(prior.lessons, current.lessons), _change(prior.uses, current.uses))

        if status != "retained" or item.lessons != Change() or item.uses != Change():
            result.append(item)

    return tuple(result)


def visits(events: Sequence[Checkpoint]) -> tuple[Checkpoint, ...]:
    """
    Collapse consecutive commits in one project to the final state of that visit.

    Args:
        events (Sequence[Checkpoint]): Validated journal in append order.

    Returns:
        tuple[Checkpoint, ...]: Visit endpoints in chronological order; returning to a project creates another visit.
    """
    result: list[Checkpoint] = []

    for event in events:
        if result and result[-1].project == event.project:
            result[-1] = event
        else:
            result.append(event)

    return tuple(result)
