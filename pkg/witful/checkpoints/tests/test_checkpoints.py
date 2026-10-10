"""
Verify checkpoint chronology, evidence accounting, portable replay, and CLI boundaries.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from witful.checkpoints.cli import main
from witful.checkpoints.diff import compare, visits
from witful.checkpoints.journal import checkpoint_id, read, record, validate
from witful.checkpoints.models import Checkpoint, Fact
from witful.checkpoints.plotting import build
from witful.checkpoints.snapshot import snapshot
from witful.checkpoints.storage import SQLiteCheckpointStore
from witful.knowledge.applications import application_id
from witful.knowledge.models import Application, Discipline, Identity, Insight, Lesson, Skill

if TYPE_CHECKING:
    from pathlib import Path


def test_snapshot_distinguishes_revision_from_new_use() -> None:
    """
    Count overlapping descendants once and retain revisions without inflating applications.

    Returns:
        None: Only active lessons and latest task observations contribute to each skill.
    """
    old = Lesson("old", "Before", "Old guidance", "Fixture", "2026-01-01T00:00:00Z")
    new = Lesson(
        "new",
        "After",
        "New guidance",
        "Fixture",
        "2026-01-02T00:00:00Z",
        supersedes="old",
        insights=(Insight("insight", "Detail", "Specific guidance", "Fixture"),),
    )
    identity = Identity("root", "Fixture", (Discipline("d", "Design", (Skill("s", "Schemas", (old, new)),)),))
    first = Application("", "task", "d", ("insight", "new", "s"), "unassessed", "Synthetic result", "2026-01-02T00:00:00Z")
    first = evolve(first, id=application_id(first))
    revised = evolve(first, id="", outcome="verified", observed_at="2026-01-03T00:00:00Z")
    revised = evolve(revised, id=application_id(revised))
    before = Checkpoint("", None, "example/one", "a" * 40, "2026-01-02T00:00:00Z", snapshot(identity, [first]))
    after = evolve(before, skills=snapshot(identity, [first, revised]))
    changes = compare(before, after)
    assert [fact.id for fact in after.skills[0].lessons] == ["new"]
    assert len(after.skills[0].uses) == 1
    assert len(changes[0].uses.revised) == 1
    assert not changes[0].uses.added
    assert compare(after, after) == ()


def test_record_retries_commit_progress_and_returning_visits(collection: Path) -> None:
    """
    Keep retry identity stable while preserving successive commits and repeated project visits.

    Args:
        collection (Path): Synthetic committed collection.

    Returns:
        None: Commit checkpoints remain available while contiguous visits collapse only for display.
    """
    first = record(collection, collection, "example/one")
    assert record(collection, collection, "example/one") == first
    subprocess.run(
        [
            "git",
            "-C",
            str(collection),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "Next boundary",
        ],
        check=True,
    )
    second = record(collection, collection, "example/one")
    third = record(collection, collection, "example/two")
    fourth = record(collection, collection, "example/one")
    events = read(collection / "knowledge/checkpoints.jsonl")
    assert events == (first, second, third, fourth)
    assert visits(events) == (second, third, fourth)
    assert compare(first, second) == ()
    assert first.revision != second.revision


def test_tampering_and_duplicate_facts_fail(collection: Path) -> None:
    """
    Reject edited history even when a caller recalculates the record ID around invalid facts.

    Args:
        collection (Path): Synthetic collection.

    Returns:
        None: Chain and canonical uniqueness checks enforce independent constraints.
    """
    first = record(collection, collection, "example/one")

    with pytest.raises(ValueError, match="history chain"):
        validate([evolve(first, project="example/changed")])

    skill = first.skills[0]
    changed = evolve(first, skills=(evolve(skill, lessons=skill.lessons * 2),))
    changed = evolve(changed, id=checkpoint_id(changed))

    with pytest.raises(ValueError, match="unique sorted"):
        validate([changed])


def test_git_failure_does_not_write_a_checkpoint(collection: Path, tmp_path: Path) -> None:
    """
    Require a real committed project rather than inventing a boundary from a directory name.

    Args:
        collection (Path): Existing source collection.
        tmp_path (Path): Directory outside its Git checkout.

    Returns:
        None: No checkpoint file is created for an invalid project.
    """
    with pytest.raises(ValueError, match="committed HEAD"):
        record(collection, tmp_path, "example/missing")

    assert not (collection / "knowledge/checkpoints.jsonl").exists()


def test_cli_local_capture_ignores_remote_endpoint(collection: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep recording local even when a separate remote synchronization endpoint is configured.

    Args:
        collection (Path): Valid committed collection.
        monkeypatch (pytest.MonkeyPatch): Isolated environment configuration.

    Returns:
        None: Source and SQLite mirror agree without initiating a PostgreSQL connection.
    """
    monkeypatch.setenv("WITFUL_DATABASE_URL", "invalid")
    assert main(["--repo", str(collection), "record", "--project", str(collection), "--project-id", "example/one"]) == 0
    assert main(["--repo", str(collection), "check"]) == 0
    assert SQLiteCheckpointStore(collection / ".witful/checkpoints.sqlite3").load() == read(collection / "knowledge/checkpoints.jsonl")

    with pytest.raises(SystemExit) as error:
        main(["--repo", str(collection), "sync"])

    assert error.value.code == 2


def test_empty_and_changed_plots_are_reproducible(collection: Path, tmp_path: Path) -> None:
    """
    Retain baseline semantics, all comparison data, and byte-stable rendering in one toolchain.

    Args:
        collection (Path): Synthetic baseline source.
        tmp_path (Path): Isolated artifact output root.

    Returns:
        None: The baseline is not reported as new learning; repeat outputs match exactly.
    """
    first = record(collection, collection, "example/one")
    second = evolve(first, previous=first.id, project="example/two", skills=(evolve(first.skills[0], uses=(Fact("task", "b" * 64),)),))
    second = evolve(second, id=checkpoint_id(second))
    empty = build([], tmp_path / "empty")
    assert len(empty) == 5
    outputs = build([first, second], tmp_path / "plots")
    contents = {path.name: path.read_bytes() for path in outputs}
    build([first, second], tmp_path / "plots")
    assert all(path.read_bytes() == contents[path.name] for path in outputs)
    payload = json.loads((tmp_path / "plots/checkpoints.json").read_text())
    assert len(payload["commit_diffs"]) == 1
    assert payload["commit_diffs"][0]["skills"][0]["uses"]["added"] == ["task"]
    assert payload["latest_vs_previous_visits"][0]["before"] == first.id


def test_skill_rename_and_removal_are_not_learning(collection: Path) -> None:
    """
    Show structural changes distinctly from new teaching and use observations.

    Args:
        collection (Path): Synthetic collection.

    Returns:
        None: Renames and removals retain their explicit status and set changes.
    """
    first = record(collection, collection, "example/one")
    renamed = evolve(first, skills=(evolve(first.skills[0], name="Contracts"),))
    assert compare(first, renamed)[0].status == "renamed"
    assert not compare(first, renamed)[0].lessons.added
    removed = compare(first, evolve(first, skills=()))[0]
    assert removed.status == "removed"
    assert removed.lessons.removed == (first.skills[0].lessons[0].id,)
