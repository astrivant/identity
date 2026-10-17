"""
Keep intent operations recursively composed and machine-readable without eager runtime loading.
"""

from __future__ import annotations

import pytest
from witful.cli import build_parser
from witful.intent.models import Query, Result, State
from witful.knowledge.contracts import schema


@pytest.mark.parametrize("operation", ["draft", "find", "explain", "coverage", "preflight", "affected"])
def test_read_only_leaves(operation: str) -> None:
    """
    Preserve the selected operation and budgets without exposing an execution switch.

    Args:
        operation (str): Explicit read-only facade leaf.

    Returns:
        None: The parser selects the lazy intent module with exact arguments.
    """
    parsed = build_parser().parse_args(["intent", operation, "value", "--client", "/protected/client.json", "--pipe", "--tokens", "12000"])
    assert parsed.handler.module == "witful.intent.cli" and parsed.handler.name == operation
    assert parsed.value == "value" and parsed.tokens == 12000
    assert not hasattr(parsed, "execute")


def test_mutations_require_explicit_predecessor_and_pipe() -> None:
    """
    Require stable operation IDs, exact predecessor choice and an admitted output sink.

    Returns:
        None: Missing mutation or custody inputs fail at parsing.
    """
    parser = build_parser()
    common = ["intent", "publish", "--client", "/protected/client.json", "--operation", "operation"]
    with pytest.raises(SystemExit):
        parser.parse_args([*common, "--pipe"])
    with pytest.raises(SystemExit):
        parser.parse_args([*common, "--initial"])
    assert parser.parse_args([*common, "--pipe", "--initial"]).expected is None


def test_closed_schema_keeps_authority_and_completeness_distinct() -> None:
    """
    Expose closed machine contracts without a boolean that could mean both completion and permission.

    Returns:
        None: Every facade model has a generated closed schema; authority has no allowed success value.
    """
    for model in (State, Query, Result):
        assert schema(model)["additionalProperties"] is False
    fields = schema(Result)["properties"]
    assert isinstance(fields, dict)
    assert fields["execution_authority"]["enum"] == ["not-evaluated"]
    assert fields["readiness"]["enum"] == ["not-evaluated", "blocked"]
