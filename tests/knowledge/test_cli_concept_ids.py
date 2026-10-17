"""
Keep full concept identifiers stable as the hierarchy gains prefix-sharing nodes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from witful.knowledge.applications import read_applications
from witful.knowledge.cli import main
from witful.knowledge.contracts import as_data
from witful.knowledge.models import Catalog, DisciplineSpec, SkillSpec

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("skill:python", "skill:python"),
        ("skill:python-p", "skill:python-publication"),
        ("skill:py", None),
        ("missing", None),
    ],
)
def test_record_resolves_exact_ids_before_prefixes(tmp_path: Path, requested: str, expected: str | None) -> None:
    """
    Accept full identifiers and unique abbreviations without weakening ambiguity rejection.

    Args:
        tmp_path (Path): Isolated synthetic collection.
        requested (str): Full identifier, abbreviation or invalid selection.
        expected (str | None): Recorded concept ID, or None for a rejected request.

    Returns:
        None: Successful records target one exact concept; rejected requests leave the journal empty.
    """
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (tmp_path / "lessons.jsonl").write_text("")
    catalog = Catalog(
        "example",
        "Synthetic identifiers",
        disciplines=(
            DisciplineSpec(
                "discipline:software",
                "Software",
                (SkillSpec("skill:python", "Python"), SkillSpec("skill:python-publication", "Publication")),
            ),
        ),
    )
    (knowledge / "catalog.json").write_text(json.dumps(as_data(catalog)))
    journal = knowledge / "applications.jsonl"
    journal.touch()
    arguments = [
        "--repo",
        str(tmp_path),
        "record",
        "--task",
        "concept-resolution",
        "--discipline",
        "discipline:software",
        "--concept",
        requested,
        "--evidence",
        "Synthetic exact identifier regression",
    ]

    if expected is None:
        with pytest.raises(SystemExit) as failure:
            main(arguments)

        assert failure.value.code == 2
        assert journal.read_bytes() == b""
    else:
        assert main(arguments) == 0
        assert read_applications(journal)[0].concept_ids == (expected,)
