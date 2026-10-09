"""
Exercise the command boundary without touching the real archive or any service.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import TYPE_CHECKING

import pytest
from witful.knowledge.cli import main
from witful.knowledge.contracts import as_data, schema
from witful.knowledge.models import Application, Catalog, DisciplineSpec, SkillSpec
from witful.lessons import new_lesson

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture, MonkeyPatch


def test_cli_checks_records_and_preserves_invalid_inputs(tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    """
    Verify the installed command's validation, inspection, idempotence, and failure boundary.

    Args:
        tmp_path (Path): Synthetic checkout directory.
        monkeypatch (MonkeyPatch): Controlled command arguments.
        capsys (CaptureFixture[str]): Captured JSON output and error messages.

    Returns:
        None: Real files contain only validated records and stale schemas fail visibly.
    """
    knowledge = tmp_path / "knowledge"
    (knowledge / "schemas").mkdir(parents=True)
    lesson = new_lesson("Topic", "Validate inputs.", "Fixture", "2026-01-01T00:00:00Z")
    (tmp_path / "lessons.jsonl").write_text(json.dumps(asdict(lesson)) + "\n")
    catalog = Catalog("root", "Example", disciplines=(DisciplineSpec("d", "Design", (SkillSpec("s", "Schema", ("Topic",)),)),))
    (knowledge / "catalog.json").write_text(json.dumps(as_data(catalog)))
    journal = knowledge / "applications.jsonl"
    journal.touch()

    for name, model in (("catalog", Catalog), ("application", Application)):
        (knowledge / f"schemas/{name}.schema.json").write_text(json.dumps(schema(model)))

    def run(*arguments: str) -> int:
        """
        Invoke the real parser against a temporary checkout.

        Args:
            *arguments (str): Arguments after the checkout selection.

        Returns:
            int: CLI exit status, or a propagated parser exit on invalid input.
        """
        monkeypatch.setattr(sys, "argv", ["witful", "--repo", str(tmp_path), *arguments])
        return main()

    assert run("check") == 0
    capsys.readouterr()
    assert run("show", "s") == 0
    assert json.loads(capsys.readouterr().out)["usage"]["applications"] == 0
    arguments = ("record", "--task", "fixture", "--discipline", "d", "--concept", lesson.id[:12], "--evidence", "Synthetic check")
    assert run(*arguments) == 0
    original = journal.read_bytes()
    assert run(*arguments) == 0
    assert journal.read_bytes() == original

    with pytest.raises(SystemExit) as failure:
        run(*arguments, "--concept", "missing")

    assert failure.value.code == 2
    assert journal.read_bytes() == original
    (knowledge / "schemas/application.schema.json").write_text("{}")

    with pytest.raises(SystemExit) as failure:
        run("check")

    assert failure.value.code == 2
    assert "schemas are stale" in capsys.readouterr().err
