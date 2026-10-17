"""
Select bounded decision paths without inventing connections between independent choices.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import frozen

from witful.life.contracts import current_decisions, validate_archive
from witful.life.models import Event  # noqa: TC001 - cattrs resolves Lane annotations at runtime.

if TYPE_CHECKING:
    from witful.life.models import Archive

__all__ = ["Lane", "Paths", "select", "lookup"]


@frozen
class Lane:
    """
    Retain the latest explicit revisions of one decision subject.

    Attributes:
        events (tuple[Event, ...]): Visible suffix, in journal order, ending at the current head.
        omitted (int): Earlier revisions retained in the complete archive.
    """

    events: tuple[Event, ...]
    omitted: int


@frozen
class Paths:
    """
    Bound presentation while accounting for every omitted source event.

    Attributes:
        lanes (tuple[Lane, ...]): Most recently updated subjects first.
        omitted_subjects (int): Subjects outside this overview.
        omitted_events (int): Events outside the displayed lane suffixes.
        total_events (int): Full journal size, including retired choices.
    """

    lanes: tuple[Lane, ...]
    omitted_subjects: int
    omitted_events: int
    total_events: int


def select(archive: Archive, *, subjects: int = 8, revisions: int = 5) -> Paths:
    """
    Keep recent subjects and their explicit revision suffixes in deterministic journal order.

    Args:
        archive (Archive): Complete validated history and snapshots.
        subjects (int): Positive maximum number of visible subjects.
        revisions (int): Positive maximum visible events per subject.

    Returns:
        Paths: Bounded view with exact omission counts; source records remain untouched.

    Raises:
        ValueError: Bounds are invalid or the source archive is corrupt.
    """
    if subjects < 1 or revisions < 1:
        raise ValueError("Decision path bounds must be positive")
    validate_archive(archive)
    groups: dict[str, list[Event]] = {}
    latest: dict[str, int] = {}
    for ordinal, event in enumerate(archive.events):
        groups.setdefault(event.decision.key, []).append(event)
        latest[event.decision.key] = ordinal

    # Wall-clock order may differ from journal order. Only explicit supersession creates a path.
    keys = sorted(groups, key=lambda key: -latest[key])[:subjects]
    lanes = tuple(Lane(tuple(groups[key][-revisions:]), max(0, len(groups[key]) - revisions)) for key in keys)
    visible = sum(len(lane.events) for lane in lanes)
    return Paths(lanes, len(groups) - len(lanes), len(archive.events) - visible, len(archive.events))


def lookup(
    archive: Archive,
    *,
    key: str | None = None,
    concept: str | None = None,
    task: str | None = None,
    history: bool = False,
    limit: int | None = None,
) -> tuple[Event, ...]:
    """
    Retrieve exact relevant decisions before making a related choice.

    Args:
        archive (Archive): Complete local decision archive.
        key (str | None): Exact stable subject filter.
        concept (str | None): Exact directly referenced concept, without inferred ancestry.
        task (str | None): Exact task identifier filter.
        history (bool): Include superseded events; otherwise match current heads only.
        limit (int | None): Keep the latest matching events in journal order, or all matches.

    Returns:
        tuple[Event, ...]: Conjunctively filtered events, including explicit retirements.

    Raises:
        ValueError: Limit is nonpositive or the archive is invalid.
    """
    if limit is not None and limit < 1:
        raise ValueError("Decision lookup limit must be positive")
    heads = current_decisions(archive)
    events = archive.events if history else heads
    selected = tuple(
        event
        for event in events
        if (key is None or event.decision.key == key)
        and (concept is None or concept in event.decision.concept_ids)
        and (task is None or event.decision.task == task)
    )
    if limit is None:
        return selected
    ordinals = {event.id: ordinal for ordinal, event in enumerate(archive.events)}
    return tuple(sorted(selected, key=lambda event: ordinals[event.id])[-limit:])
