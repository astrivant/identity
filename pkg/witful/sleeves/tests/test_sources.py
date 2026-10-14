"""
Keep private source snapshots isolated and prevent closure while plaintext observations remain unsaved.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from witful.collection import operations as collection
from witful.collection.keys import prepare
from witful.collection.models import CONFIG, SOURCE
from witful.exceptions import SleeveError
from witful.knowledge.contracts import as_data
from witful.project import main as initialize
from witful.sleeves import operations, state
from witful.sleeves.git import git

if TYPE_CHECKING:
    import subprocess

    from pytest import MonkeyPatch


@pytest.mark.skipif(shutil.which("cosign") is None, reason="Cosign required for real signed encrypted transport")
def test_encrypted_instances_preserve_snapshots_and_block_unsaved_closure(
    repository: Path,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Restore isolated sources, encrypt backups, and preserve both versions when concurrent ciphertext conflicts.

    Args:
        repository (Path): Synthetic Git repository.
        tmp_path (Path): Private local sources and keys.
        monkeypatch (MonkeyPatch): Replace GitHub visibility while exercising real crypto and Git.

    Returns:
        None: Plaintext never enters Git and a conflicting encrypted snapshot cannot silently win.
    """
    monkeypatch.setattr(collection, "private_repository", lambda repository: None)
    monkeypatch.setattr(collection, "require_protected", lambda path: None)
    source, keys = tmp_path / "seed", tmp_path / "keys"
    initialize([str(source)])
    (source / "instructions.md").write_text("SYNTHETIC_PRIVATE_BASE")
    config = prepare(keys, "example/identity")
    (repository / ".config").mkdir()
    (repository / "collection").mkdir()
    (repository / CONFIG).write_text(json.dumps(as_data(config)))
    (repository / "collection/cosign.pub").write_bytes((keys / "cosign.pub").read_bytes())
    collection.seal(repository, source, keys)
    git(repository, "add", ".config/collection.json", "collection")
    git(repository, "-c", "commit.gpgsign=true", "commit", "-m", "Encrypted seed")
    git(repository, "push", "origin", "main")
    first = operations.start(repository, tmp_path / "first", name="first", keys=keys)
    second = operations.start(repository, tmp_path / "second", name="second", keys=keys)
    before = git(Path(first.worktree), "rev-parse", "HEAD").stdout
    operations.checkpoint(Path(first.worktree), (), "No source change")
    assert git(Path(first.worktree), "rev-parse", "HEAD").stdout == before
    first_source, second_source = tmp_path / "first/source", tmp_path / "second/source"
    assert (first_source / "instructions.md").read_text() == "SYNTHETIC_PRIVATE_BASE"
    (first_source / "instructions.md").write_text("SYNTHETIC_PRIVATE_FIRST")
    assert (second_source / "instructions.md").read_text() == "SYNTHETIC_PRIVATE_BASE"

    with pytest.raises(SleeveError, match="uncheckpointed plaintext"):
        operations.finish(Path(first.worktree))

    for sleeve, root, value in ((first, first_source, "FIRST"), (second, second_source, "SECOND")):
        (root / "instructions.md").write_text("SYNTHETIC_PRIVATE_" + value)

        def edit_during_push(cwd: Path, *arguments: str, allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
            """
            Simulate another local write after the snapshot is sealed but before publication completes.

            Args:
                cwd (Path): Sleeve worktree.
                *arguments (str): Git operation.
                allowed (tuple[int, ...]): Accepted process statuses.

            Returns:
                subprocess.CompletedProcess[str]: Real Git result, with a later plaintext edit retained locally.
            """
            if arguments[:1] == ("push",):
                (Path(state.current(cwd).directory) / "source/instructions.md").write_text("SYNTHETIC_PRIVATE_LATER")
            return git(cwd, *arguments, allowed=allowed)

        with monkeypatch.context() as local:
            local.setattr(operations, "git", edit_during_push)
            operations.checkpoint(Path(sleeve.worktree), (), "Encrypted observation")

        with pytest.raises(SleeveError, match="uncheckpointed plaintext"):
            operations.finish(Path(sleeve.worktree))

        # Restore the exact backed-up snapshot for the independent merge-conflict assertion below.
        (root / "instructions.md").write_text("SYNTHETIC_PRIVATE_" + value)
        assert b"SYNTHETIC_PRIVATE" not in (Path(sleeve.worktree) / SOURCE).read_bytes()
        assert git(Path(sleeve.worktree), "status", "--porcelain").stdout == ""

    operations.finish(Path(first.worktree))
    with pytest.raises(SleeveError, match="Merge blocked"):
        operations.finish(Path(second.worktree))
    assert state.current(Path(second.worktree)).closed_commit is None
    assert (second_source / "instructions.md").read_text() == "SYNTHETIC_PRIVATE_SECOND"
    assert not git(Path(second.worktree), "ls-files", "*source/instructions.md").stdout
