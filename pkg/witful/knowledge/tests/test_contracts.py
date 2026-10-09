"""
Check source boundaries, preserved provenance, and deterministic hierarchy compilation.
"""

from __future__ import annotations

import pytest
from attrs import evolve
from jsonschema import ValidationError
from witful.knowledge.compiler import compile_identity, index
from witful.knowledge.contracts import as_data, structure
from witful.knowledge.models import Annotation, Catalog, DisciplineSpec, Identity, Lemma, Lesson, Relation, SkillSpec
from witful.lessons import new_lesson


@pytest.mark.parametrize("bad", [{"extra": 1}, {"version": True}, {"version": "1"}, {"disciplines": {}}, {"name": 2}])
def test_source_rejects_coercion_and_unknown_fields(bad: dict[str, object]) -> None:
    """
    Fail before cattrs can silently coerce malformed source inputs.

    Args:
        bad (dict[str, object]): Invalid override of otherwise valid catalog fields.

    Returns:
        None: Closed generated schemas reject every malformed source.
    """
    with pytest.raises(ValidationError):
        structure({"id": "root", "name": "Example", **bad}, Catalog)


def test_archive_preservation_roundtrip_and_input_order() -> None:
    """
    Preserve original observations through classification, annotation, and serialization.

    Returns:
        None: Every source record appears once with exact provenance and deterministic ordering.
    """
    first = new_lesson("Compiler", "Use explicit inputs.", "Synthetic teaching", "2026-01-01T00:00:00Z")
    second = new_lesson("Compiler", "Use explicit context too.", "Synthetic correction", "2026-01-02T00:00:00Z", first.id)
    catalog = Catalog(
        "root",
        "Example",
        disciplines=(DisciplineSpec("design", "Design", (SkillSpec("compiler", "Compilers", ("Compiler",)),)),),
        annotations=(Annotation(first.id, "Explicit inputs", (Lemma("inputs", "Inputs", "Pass context.", "Synthetic decomposition"),)),),
    )
    compiled = compile_identity((first, second), catalog)
    assert compiled == compile_identity((second, first), catalog)
    assert structure(as_data(compiled), Identity) == compiled
    nodes, _ = index(compiled)

    for record in (first, second):
        lesson = nodes[record.id]
        assert isinstance(lesson, Lesson)
        assert (lesson.statement, lesson.source, lesson.observed_at, lesson.supersedes) == (
            record.lesson,
            record.source,
            record.observed_at,
            record.supersedes,
        )


def test_minimal_and_unclassified_profiles() -> None:
    """
    Keep sparse collections valid and preserve newly taught topics without guessing their field.

    Returns:
        None: Empty inputs work and unknown subjects have stable explicit homes.
    """
    catalog = Catalog("root", "Example")
    assert compile_identity((), catalog) == Identity("root", "Example")
    lesson = new_lesson("New subject", "New guidance.", "Fixture", "2026-01-01T00:00:00Z")
    compiled = compile_identity((lesson,), catalog)
    assert compiled.disciplines[0].id == "discipline:unclassified"
    assert compiled.disciplines[0].skills[0].lessons[0].id == lesson.id


@pytest.mark.parametrize("kind", ["related", "requires"])
def test_only_prerequisites_require_acyclicity(kind: str) -> None:
    """
    Permit reciprocal conceptual reuse while rejecting impossible prerequisite ordering.

    Args:
        kind (str): Relationship semantics under test.

    Returns:
        None: Requirements cycles fail and general relationships remain graph-shaped.
    """
    value = {
        "id": "root",
        "name": "Example",
        "disciplines": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        "relations": [
            {"source": "a", "target": "b", "kind": kind, "evidence": "Fixture"},
            {"source": "b", "target": "a", "kind": kind, "evidence": "Fixture"},
        ],
    }
    catalog = structure(value, Catalog)

    if kind == "requires":
        with pytest.raises(ValueError, match="acyclic"):
            compile_identity((), catalog)
    else:
        assert len(compile_identity((), catalog).relations) == 2


def test_ambiguous_ownership_and_dangling_relationships_fail() -> None:
    """
    Reject catalog edits that could duplicate lessons or attach false references.

    Returns:
        None: Invalid ownership, IDs, annotations, and edges cannot compile.
    """
    catalog = Catalog("root", "Example", disciplines=(DisciplineSpec("a", "A", (SkillSpec("one", "One", ("Topic",)),)),))
    invalid = (
        evolve(catalog, disciplines=(*catalog.disciplines, DisciplineSpec("b", "B", (SkillSpec("two", "Two", ("Topic",)),)))),
        evolve(catalog, disciplines=(*catalog.disciplines, catalog.disciplines[0])),
        evolve(catalog, annotations=(Annotation("missing", "Missing"),)),
        evolve(catalog, relations=(Relation("one", "missing", "related", "Fixture"),)),
    )

    for item in invalid:
        with pytest.raises(ValueError):
            compile_identity((), item)
