"""
Exercise deterministic source projection, protocol rejection, and journal ownership.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from mcp import types
from witful.knowledge.contracts import as_data, schema, structure
from witful.lessons import append_lesson, new_lesson
from witful.project import main as initialize
from witful.sapience.cli import main
from witful.sapience.client import decode
from witful.sapience.models import Projection
from witful.sapience.projection import project

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def collection(tmp_path: Path) -> Path:
    """
    Create a synthetic collection with an explicit correction and no private data.

    Args:
        tmp_path (Path): Isolated test parent directory.

    Returns:
        Path: Collection containing two reviewed journal records.
    """
    root = tmp_path / "collection"
    assert initialize([str(root)]) == 0
    first = new_lesson("Review", "Review publication inputs.", "fixture:one", "2026-01-01T00:00:00+00:00")
    second = new_lesson("Review", "Review publication inputs and outputs.", "fixture:two", "2026-02-01T00:00:00+00:00", first.id)
    append_lesson(root / "lessons.jsonl", first)
    append_lesson(root / "lessons.jsonl", second)
    return root


def test_projection_is_stable_and_retains_supersession(collection: Path) -> None:
    """
    Repeated projections retain source IDs, lineage, exact attribution, and historical status.

    Args:
        collection (Path): Two-record source fixture.

    Returns:
        None: Serialization round-trips and changing the destination partitions IDs.
    """
    before = (collection / "lessons.jsonl").read_bytes()
    result = project(collection, "fixture", "reviewed")
    assert result == project(collection, "fixture", "reviewed")
    assert structure(as_data(result), Projection) == result
    lessons = [item for item in result.memories if item.metadata.kind == "lesson"]
    assert len(lessons) == 2
    old = next(item for item in lessons if item.metadata.status == "historical")
    new = next(item for item in lessons if item.metadata.status == "active")
    assert new.metadata.supersedes == old.metadata.source_id
    assert old.memory_id in new.related_ids
    assert new.metadata.source_ref == "fixture:two"
    assert str(collection) not in json.dumps(as_data(result))
    assert not {item.memory_id for item in result.memories} & {item.memory_id for item in project(collection, "other", "reviewed").memories}
    assert (collection / "lessons.jsonl").read_bytes() == before


@pytest.mark.parametrize("namespace", ["*", "", "space here"])
def test_invalid_namespace_is_rejected(collection: Path, namespace: str) -> None:
    """
    Disallow wildcard or ambiguous destinations before any external operation.

    Args:
        collection (Path): Existing source fixture.
        namespace (str): Invalid caller-selected partition.

    Returns:
        None: Invalid namespace has no usable projection.
    """
    with pytest.raises(ValueError, match="namespace"):
        project(collection, "fixture", namespace)


def test_export_stays_local_and_leaves_source_untouched(collection: Path) -> None:
    """
    Exercise the CLI without invoking an MCP server or a model provider.

    Args:
        collection (Path): Existing source fixture.

    Returns:
        None: Only the ignored review artifact is created and validates against the public schema.
    """
    before = (collection / "lessons.jsonl").read_bytes()
    assert main(["--repo", str(collection), "export", "--collection-id", "fixture", "--namespace", "reviewed"]) == 0
    output = json.loads((collection / ".witful/sapience-projection.json").read_text())
    assert structure(output, Projection) == project(collection, "fixture", "reviewed")
    assert (collection / "lessons.jsonl").read_bytes() == before


def test_protocol_errors_and_disagreements_are_rejected() -> None:
    """
    Reject both modern failures and legacy error envelopes instead of trusting textual JSON.

    Returns:
        None: Only consistent, schema-valid successful results can cross the adapter boundary.
    """
    data = {"version": 1, "memories": []}
    text = types.TextContent(type="text", text=json.dumps(data))
    assert decode(types.CallToolResult(content=[text]), schema(Projection)) == data
    assert decode(types.CallToolResult(content=[text], structured_content=data), schema(Projection)) == data

    for result in (
        types.CallToolResult(content=[text], is_error=True),
        types.CallToolResult(content=[types.TextContent(type="text", text='{"error":"private provider response"}')]),
        types.CallToolResult(content=[text], structured_content={"version": 2}),
    ):
        with pytest.raises(ValueError) as error:
            decode(result, schema(Projection))
        assert "private provider response" not in str(error.value)


def test_output_override_cannot_replace_journal(collection: Path) -> None:
    """
    Reject a generated export destination that aliases a reviewed source.

    Args:
        collection (Path): Existing synthetic collection.

    Returns:
        None: The command fails without modifying the journal.
    """
    before = (collection / "lessons.jsonl").read_bytes()
    with pytest.raises(SystemExit) as error:
        main(["--repo", str(collection), "export", "--collection-id", "fixture", "--namespace", "reviewed", "--output", "lessons.jsonl"])
    assert error.value.code == 2
    assert (collection / "lessons.jsonl").read_bytes() == before
