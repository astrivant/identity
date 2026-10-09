"""
Validate and summarize observed tool use without inferring history from dependencies.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

from sapience.knowledge.contracts import as_data

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sapience.repertoire.models import Inventory, Problem, Tool, Use


def use_id(event: Use) -> str:
    """
    Hash a complete observation independently of its recording timestamp.

    Args:
        event (Use): Canonically ordered observation whose existing ID is ignored.

    Returns:
        str: Stable SHA-256 identifier for idempotent repeated observations.
    """
    payload = as_data(event)
    payload.pop("id")
    payload.pop("observed_at")
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate(inventory: Inventory, events: Sequence[Use], concepts: set[str]) -> None:
    """
    Require a valid hierarchy and evidence-bound, unambiguous observations.

    Args:
        inventory (Inventory): Reviewed source catalog.
        events (Sequence[Use]): Complete ordered history.
        concepts (set[str]): Valid IDs from the separately compiled knowledge hierarchy.

    Returns:
        None: All definitions, references, timestamps, and IDs are consistent.

    Raises:
        ValueError: Definitions are missing, cyclic, duplicated, or observations are invalid.
    """
    tools = {item.id: item for item in inventory.tools}
    problems = {item.id: item for item in inventory.problems}

    if len(tools) != len(inventory.tools) or len(problems) != len(inventory.problems) or tools.keys() & problems.keys():
        raise ValueError("Tool and problem identifiers must be unique")

    definitions: tuple[Tool | Problem, ...] = (*inventory.tools, *inventory.problems)

    for item in definitions:
        if not item.id.strip() or not item.name.strip():
            raise ValueError("Inventory definitions require nonempty identifiers and labels")

    for tool in inventory.tools:
        if not tool.purpose.strip() or not tool.reference.strip():
            raise ValueError("Tools require a purpose and source reference")

    for problem in inventory.problems:
        seen: set[str] = set()
        current: str | None = problem.id

        while current is not None:
            if current in seen or current not in problems:
                raise ValueError("Problem parents must exist and cannot form cycles")

            seen.add(current)
            current = problems[current].parent

    ids: set[str] = set()
    moments: set[tuple[str, datetime]] = set()

    for event in events:
        observed = datetime.fromisoformat(event.observed_at)

        if not event.task.strip() or not event.evidence.strip() or not event.tools or not event.problems:
            raise ValueError("Tool uses require an actual task, tools, problems, and evidence")
        if observed.tzinfo is None or (event.task, observed) in moments:
            raise ValueError("Observation times must be timezone-aware and unique per task")
        if event.id != use_id(event) or event.id in ids:
            raise ValueError("Invalid or duplicate tool-use identifier")

        for values, allowed in ((event.tools, set(tools)), (event.problems, set(problems)), (event.concepts, concepts)):
            if tuple(sorted(set(values))) != values or set(values) - allowed:
                raise ValueError("References must be known, unique, and sorted")

        ids.add(event.id)
        moments.add((event.task, observed))


def counts(inventory: Inventory, events: Sequence[Use]) -> tuple[dict[str, int], dict[str, int]]:
    """
    Count current task observations, rolling problems upward once per task.

    Args:
        inventory (Inventory): Validated toolbox and problem hierarchy.
        events (Sequence[Use]): Validated history; the latest timestamp per task owns current counts.

    Returns:
        tuple[dict[str, int], dict[str, int]]: Tool counts and inclusive problem counts, retaining zero-use definitions.
    """
    latest: dict[str, Use] = {}

    for event in sorted(events, key=lambda item: (datetime.fromisoformat(item.observed_at), item.id)):
        latest[event.task] = event

    tools: Counter[str] = Counter({item.id: 0 for item in inventory.tools})
    problems: Counter[str] = Counter({item.id: 0 for item in inventory.problems})
    parents = {item.id: item.parent for item in inventory.problems}

    for event in latest.values():
        tools.update(event.tools)
        ancestry: set[str] = set()

        for problem in event.problems:
            current: str | None = problem

            while current is not None:
                ancestry.add(current)
                current = parents[current]

        problems.update(ancestry)

    return dict(tools), dict(problems)
