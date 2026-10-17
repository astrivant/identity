"""
Supply frozen synthetic intent examples with a separately declared source universe.
"""

from __future__ import annotations

import hashlib

from witful.intent.contracts import QUERY_VERSION, SCHEMA_VERSION, fingerprint
from witful.intent.models import Anchor, Assertion, Coverage, Evidence, File, Input, Scope, Span, State
from witful.repertoire.models import Inventory, Tool


def example() -> State:
    """
    Construct a narrow inferred publication helper with exact semantic inspection coverage.

    Returns:
        State: Deterministic synthetic evidence, not a production enrollment or semantic approval.
    """
    raw = b"Publish selected paths only.\n"
    content = hashlib.sha256(raw).hexdigest()
    files = (File("contract.md", content, len(raw)),)
    inventory = Inventory((Tool("tool:publish", "Publication helper", "script", "Publish selected paths", "scripts/publish.py"),))
    inputs = tuple(
        Input(name, name, fingerprint(value), 100)
        for name, value in (
            ("inventory", inventory),
            ("query", QUERY_VERSION),
            ("schema", SCHEMA_VERSION),
            ("parser", "direct/1"),
            ("configuration", {}),
            ("dependency-locks", "synthetic-lock"),
        )
    )
    scope = Scope(
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
        "00000000-0000-4000-8000-000000000003",
        "a" * 40,
        fingerprint(files),
        "00000000-0000-4000-8000-000000000004",
    )
    return State(
        scope,
        inventory,
        inputs,
        files,
        (Anchor("anchor:contract", "contract.md", content, 0, len(raw), "direct/1", "exact-bytes"),),
        (
            Coverage(
                "coverage:contract",
                scope.manifest,
                (Span("contract.md", 0, len(raw), "inspected"),),
                ("contract.md",),
                "semantic",
                "fixture-reviewer",
                "What paths does the contract permit?",
                ("contract-only",),
                100,
            ),
        ),
        (
            Evidence(
                "evidence:contract",
                "intent_declaration",
                "anchor:contract",
                content,
                "maintainer-contract",
                100,
                ("anchor:contract",),
                raw.decode(),
            ),
        ),
        (
            Assertion(
                "claim:publish",
                "tool:publish",
                ("anchor:contract",),
                "The helper intends to publish selected paths only.",
                "Explicit path selection",
                "inference",
                ("evidence:contract",),
                (),
                (),
                (),
                100,
            ),
        ),
        (),
        (),
        (),
    )
