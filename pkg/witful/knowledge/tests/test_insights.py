"""
Preserve historical provenance while exposing Insights in current models.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from jsonschema import ValidationError
from witful.checkpoints.snapshot import digest, snapshot
from witful.knowledge.compiler import compile_identity, index
from witful.knowledge.contracts import as_data, structure
from witful.knowledge.models import Annotation, Catalog, DisciplineSpec, Insight, SkillSpec
from witful.lessons import append_lesson, new_lesson
from witful.life.contracts import canonical, content_id, snapshot_identity
from witful.life.models import Snapshot

if TYPE_CHECKING:
    from pathlib import Path


def _catalog(lesson_id: str) -> Catalog:
    """
    Describe a sourced Insight with a stable identifier independent of its type name.

    Args:
        lesson_id (str): Existing journal record to annotate.

    Returns:
        Catalog: Current version-2 catalog with one classified lesson and one Insight.
    """
    return Catalog(
        "root",
        "Example",
        disciplines=(DisciplineSpec("design", "Design", (SkillSpec("review", "Review", ("Review",)),)),),
        annotations=(Annotation(lesson_id, "Reviewed inputs", (Insight("detail", "Evidence", "Keep evidence", "Fixture"),)),),
    )


@pytest.mark.parametrize("version,field", [(1, "lemmas"), (2, "insights")])
def test_catalog_versions_roundtrip_without_rewriting(version: int, field: str) -> None:
    """
    Translate input vocabulary without altering source objects or stable concept IDs.

    Args:
        version (int): Serialized catalog version.
        field (str): Field spelling accepted by that version.

    Returns:
        None: Versioned data round-trips and the compiled Python API uses Insight.
    """
    catalog = _catalog("lesson")
    value = as_data(evolve(catalog, version=1)) if version == 1 else as_data(catalog)
    before = deepcopy(value)
    restored = structure(value, Catalog)
    assert value == before
    assert as_data(restored) == before
    assert isinstance(restored.annotations[0].insights[0], Insight)
    assert restored.annotations[0].insights[0].id == "detail"
    annotations = value["annotations"]
    assert isinstance(annotations, list)
    assert field in annotations[0]


@pytest.mark.parametrize(
    "version,fields",
    [(1, {"insights": []}), (2, {"lemmas": []}), (1, {"lemmas": [], "insights": []}), (2, {"lemmas": [], "insights": []})],
)
def test_catalog_rejects_mixed_or_wrong_vocabulary(version: int, fields: dict[str, object]) -> None:
    """
    Reject ambiguous spellings instead of silently dropping a user's annotations.

    Args:
        version (int): Declared source format.
        fields (dict[str, object]): Annotation fields inconsistent with that format.

    Returns:
        None: The boundary fails before conversion can discard conflicting data.
    """
    value = {"id": "root", "name": "Example", "version": version, "annotations": [{"lesson_id": "lesson", "name": "Note", **fields}]}

    with pytest.raises(ValidationError):
        structure(value, Catalog)


@pytest.mark.parametrize("version", [1, 2])
def test_versionless_catalog_uses_its_existing_vocabulary(version: int) -> None:
    """
    Keep optional version fields readable without confusing legacy annotation keys.

    Args:
        version (int): Source vocabulary selected before omitting the version.

    Returns:
        None: The typed catalog retains the format implied by its keys.
    """
    catalog = _catalog("lesson")
    value = as_data(evolve(catalog, version=1)) if version == 1 else as_data(catalog)
    value.pop("version")
    assert structure(value, Catalog).version == version


def test_legacy_snapshot_retains_hash_and_detects_tampering(tmp_path: Path) -> None:
    """
    Validate an original snapshot hash without rewriting history during terminology migration.

    Args:
        tmp_path (Path): Isolated synthetic journal directory.

    Returns:
        None: Legacy snapshot bytes remain reproducible and changed content still fails verification.
    """
    lesson = new_lesson("Review", "Retain inputs", "Fixture", "2026-01-01T00:00:00Z")
    (tmp_path / "lessons.jsonl").touch()
    append_lesson(tmp_path / "lessons.jsonl", lesson)
    value: dict[str, object] = {
        "version": 1,
        "lessons_jsonl": (tmp_path / "lessons.jsonl").read_text(),
        "catalog": as_data(evolve(_catalog(lesson.id), version=1)),
        "applications": [],
        "renderer": ["fixture"],
        "source_revision": "working-tree",
    }
    identifier = hashlib.sha256(canonical(value)).hexdigest()
    value["id"] = identifier
    restored = structure(value, Snapshot)
    assert content_id(restored) == identifier
    assert as_data(restored) == value
    nodes, _ = index(snapshot_identity(restored))
    assert isinstance(nodes["detail"], Insight)

    with pytest.raises(ValueError, match="identifier"):
        snapshot_identity(evolve(restored, catalog=evolve(restored.catalog, name="Changed")))


def test_rename_does_not_count_as_revised_checkpoint_guidance() -> None:
    """
    Preserve checkpoint lesson digests so renaming a type cannot manufacture recorded growth.

    Returns:
        None: New Insight models retain the checkpoint contract's historical lesson fingerprint.
    """
    record = new_lesson("Review", "Retain inputs", "Fixture", "2026-01-01T00:00:00Z")
    identity = compile_identity((record,), _catalog(record.id))
    lesson = identity.disciplines[0].skills[0].lessons[0]
    original = as_data(lesson)
    original["lemmas"] = original.pop("insights")
    assert snapshot(identity, ())[0].lessons[0].digest == digest(original)
