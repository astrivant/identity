"""
Provide synthetic source snapshots without copying private teachings or authentication data.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from witful.knowledge.contracts import as_data
from witful.knowledge.models import Annotation, Catalog, DisciplineSpec, Insight, SkillSpec
from witful.lessons import new_lesson
from witful.life.models import Decision


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """
    Create the minimum valid source set needed to record and replay a decision.

    Args:
        tmp_path (Path): Per-test isolated directory.

    Returns:
        Path: Synthetic input set with one insight and no inferred application events.
    """
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    lesson = new_lesson("Testing", "Use explicit inputs", "Fixture", "2026-01-01T00:00:00Z")
    (tmp_path / "lessons.jsonl").write_text(json.dumps(asdict(lesson)) + "\n")
    catalog = Catalog(
        "root",
        "Fixture",
        disciplines=(DisciplineSpec("d", "Design", (SkillSpec("s", "Schemas", ("Testing",)),)),),
        annotations=(Annotation(lesson.id, "Explicit inputs", (Insight("insight", "Replay", "Retain inputs", "Fixture"),)),),
    )
    (knowledge / "catalog.json").write_text(json.dumps(as_data(catalog)))
    (knowledge / "applications.jsonl").write_text("")
    (tmp_path / "poetry.lock").write_bytes((Path(__file__).parents[4] / "poetry.lock").read_bytes())
    return tmp_path


@pytest.fixture
def decision() -> Decision:
    """
    Supply a reviewable choice with a insight reference and no revision target.

    Returns:
        Decision: Synthetic choice, not a historical observation about the user's work.
    """
    return Decision(
        "storage:journal", "Preserve history", "fixture:task", "Append revisions", "Retain prior evidence", "Fixture", ("insight",)
    )
