"""
Build synthetic checkpoint evidence in isolated committed project checkouts.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from typing import TYPE_CHECKING

import pytest
from witful.knowledge.contracts import as_data
from witful.knowledge.models import Catalog, DisciplineSpec, SkillSpec
from witful.lessons import new_lesson

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def collection(tmp_path: Path) -> Path:
    """
    Create one synthetic teaching and an empty application journal.

    Args:
        tmp_path (Path): Isolated test directory.

    Returns:
        Path: Valid collection inside a Git checkout with one committed boundary.
    """
    root = tmp_path / "collection"
    (root / "knowledge").mkdir(parents=True)
    lesson = new_lesson("Testing", "Record explicit inputs", "Synthetic fixture", "2026-01-01T00:00:00Z")
    (root / "lessons.jsonl").write_text(json.dumps(asdict(lesson)) + "\n")
    catalog = Catalog("identity:test", "Fixture", disciplines=(DisciplineSpec("d", "Design", (SkillSpec("s", "Schemas", ("Testing",)),)),))
    (root / "knowledge/catalog.json").write_text(json.dumps(as_data(catalog)))
    (root / "knowledge/applications.jsonl").write_text("")
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "Synthetic boundary",
        ],
        check=True,
    )
    return root
