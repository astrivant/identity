"""
Verify taxonomy totality, revision counts, schema closure, and evidence requirements.
"""

from __future__ import annotations

import pytest
from attrs import evolve
from jsonschema import ValidationError
from sapience.knowledge.contracts import as_data, structure
from sapience.repertoire.journal import counts, use_id, validate
from sapience.repertoire.models import Inventory, Problem, Tool, Use


def fixture() -> tuple[Inventory, Use]:
    """
    Create a synthetic task that exercises both concrete and abstract problem categories.

    Returns:
        tuple[Inventory, Use]: Minimal definition set and one actual-use stand-in.
    """
    inventory = Inventory(
        (Tool("t", "Checker", "script", "Validate input", "Fixture"), Tool("unused", "Unused", "command", "Inspect", "Fixture")),
        (Problem("broad", "Verification"), Problem("specific", "Contract check", "broad")),
    )
    draft = Use("", "task", ("t",), ("broad", "specific"), ("concept",), "Synthetic verified outcome", "2026-01-01T00:00:00Z")
    return inventory, evolve(draft, id=use_id(draft))


def test_counts_use_latest_task_and_deduplicate_ancestors() -> None:
    """
    Count current evidence rather than revisions, dependencies, or duplicate ancestry.

    Returns:
        None: Each task contributes once to a tool and each inclusive problem ancestor.
    """
    inventory, first = fixture()
    revised = evolve(first, tools=("unused",), observed_at="2026-01-02T00:00:00Z")
    revised = evolve(revised, id=use_id(revised))
    validate(inventory, [first, revised], {"concept"})
    tools, problems = counts(inventory, [first, revised])
    assert tools == {"t": 0, "unused": 1}
    assert problems == {"broad": 1, "specific": 1}
    assert counts(inventory, []) == ({"t": 0, "unused": 0}, {"broad": 0, "specific": 0})
    assert structure(as_data(inventory), Inventory) == inventory


def test_invalid_taxonomy_and_evidence_fail() -> None:
    """
    Reject unknown references, cycles, duplicate identities, and unsupported source fields.

    Returns:
        None: Invalid sources cannot produce misleading frequency plots.
    """
    inventory, event = fixture()
    invalid = [
        evolve(inventory, problems=(Problem("broad", "Root", "missing"),)),
        evolve(inventory, problems=(Problem("broad", "Root", "specific"), Problem("specific", "Leaf", "broad"))),
        evolve(inventory, tools=inventory.tools + inventory.tools),
    ]

    for candidate in invalid:
        with pytest.raises(ValueError):
            validate(candidate, [], set())

    for observation in (evolve(event, evidence=""), evolve(event, tools=("absent",)), evolve(event, observed_at="2026-01-01")):
        with pytest.raises(ValueError):
            validate(inventory, [observation], {"concept"})

    with pytest.raises(ValueError):
        validate(inventory, [event, event], {"concept"})

    with pytest.raises(ValidationError):
        structure({**as_data(inventory), "guessed_proficiency": 100}, Inventory)
