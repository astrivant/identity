"""
Distinguish committed checkpoints from failed disposable projection updates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from witful.checkpoints.cli import main
from witful.checkpoints.journal import read, record
from witful.checkpoints.storage import SQLiteCheckpointStore

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("failure", ["divergence", "directory", "corruption"])
def test_record_reports_saved_id_before_mirror_failure(collection: Path, capsys: pytest.CaptureFixture[str], failure: str) -> None:
    """
    Retain the authoritative append and report a recoverable partial result.

    Args:
        collection (Path): Synthetic collection with a committed project.
        capsys (pytest.CaptureFixture[str]): Isolated CLI output streams.
        failure (str): Real local projection failure to reproduce.

    Returns:
        None: Retrying never duplicates the event, and a separate mirror can recover it.
    """
    journal = collection / "knowledge/checkpoints.jsonl"
    record(collection, collection, "example/base")
    baseline = journal.read_bytes()
    database = collection / ".witful/checkpoints.sqlite3"
    database.parent.mkdir()
    if failure == "divergence":
        record(collection, collection, "example/other-branch")
        SQLiteCheckpointStore(database).seed(read(journal))
        journal.write_bytes(baseline)
    elif failure == "directory":
        database.mkdir()
    else:
        database.write_bytes(b"invalid SQLite with confidential diagnostic material")
    retained = database.read_bytes() if database.is_file() else None
    arguments = ["--repo", str(collection), "record", "--project", str(collection), "--project-id", "example/current"]

    for _ in range(2):
        assert main(arguments) == 3
        output = capsys.readouterr()
        events = read(journal)
        assert len(events) == 2
        assert output.out.strip() == events[-1].id
        assert "Checkpoint saved" in output.err
        assert "checkpoints sync" in output.err
        assert "confidential" not in output.err
        assert not retained or database.read_bytes() == retained

    recovered = collection / ".witful/current-branch.sqlite3"
    assert main(["--repo", str(collection), "--database", str(recovered), "sync"]) == 0
    assert SQLiteCheckpointStore(recovered).load() == read(journal)


def test_failed_source_record_does_not_claim_saved_id(collection: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """
    Keep a failed source operation distinct from a successful append with a stale mirror.

    Args:
        collection (Path): Valid source collection.
        tmp_path (Path): Uncommitted directory supplied as the project.
        capsys (pytest.CaptureFixture[str]): Isolated output streams.

    Returns:
        None: The original failure code remains and no checkpoint success is printed.
    """
    with pytest.raises(SystemExit) as error:
        main(["--repo", str(collection), "record", "--project", str(tmp_path), "--project-id", "example/missing"])
    assert error.value.code == 2
    assert not capsys.readouterr().out
    assert not (collection / "knowledge/checkpoints.jsonl").exists()
