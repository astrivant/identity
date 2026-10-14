"""
Exercise independent sleeves against real local Git remotes without GitHub or provider calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from witful.exceptions import SleeveError
from witful.sleeves import operations, state
from witful.sleeves.git import git

if TYPE_CHECKING:
    import subprocess

    from pytest import MonkeyPatch


def test_divergent_instances_converge_without_switching_primary(repository: Path, tmp_path: Path) -> None:
    """
    Preserve both signed histories and require a remotely verified merge before the close guard passes.

    Args:
        repository (Path): Synthetic Git checkout.
        tmp_path (Path): Worktree container.

    Returns:
        None: Two independent branches converge and the primary checkout stays untouched.
    """
    first = operations.start(repository, tmp_path / "first", name="first")
    second = operations.start(repository, tmp_path / "second", name="second")
    assert first.base_commit == second.base_commit
    assert first.branch != second.branch
    assert Path(first.worktree).stat().st_ino != Path(second.worktree).stat().st_ino
    for sleeve, name in ((first, "first.md"), (second, "second.md")):
        root = Path(sleeve.worktree)
        (root / name).write_text("A sourced independent observation.\n")
        operations.checkpoint(root, (name,), "Record synthetic observation")
        assert "SSH SIGNATURE" in git(root, "cat-file", "-p", "HEAD").stdout
        with pytest.raises(SleeveError, match="closure is blocked"):
            operations.guard(root)
        closed = operations.finish(root)
        operations.guard(root)
        assert closed.closed_commit is not None

    remote = git(repository, "remote", "get-url", "origin").stdout.strip()
    for name in ("first.md", "second.md"):
        assert "independent observation" in git(Path(remote), "show", "main:" + name).stdout
    assert git(repository, "rev-parse", "HEAD").stdout.strip() == first.base_commit
    assert not (repository / "first.md").exists()
    assert operations.finish(Path(second.worktree)).closed_commit == closed.closed_commit


def test_conflicting_teachings_leave_session_open(repository: Path, tmp_path: Path) -> None:
    """
    Refuse to choose between divergent instructions and preserve each remote backup.

    Args:
        repository (Path): Synthetic Git checkout.
        tmp_path (Path): Independent sleeve directories.

    Returns:
        None: Git conflict remains available for deliberate resolution without overwriting main.
    """
    first = operations.start(repository, tmp_path / "first", name="first")
    second = operations.start(repository, tmp_path / "second", name="second")
    for sleeve, content in ((first, "First policy.\n"), (second, "Second policy.\n")):
        root = Path(sleeve.worktree)
        (root / "instructions.md").write_text(content)
        operations.checkpoint(root, ("instructions.md",), "Record policy")
    operations.finish(Path(first.worktree))
    with pytest.raises(SleeveError, match="Merge blocked"):
        operations.finish(Path(second.worktree))
    assert git(Path(second.worktree), "ls-files", "--unmerged").stdout
    assert state.current(Path(second.worktree)).closed_commit is None
    remote = Path(git(repository, "remote", "get-url", "origin").stdout.strip())
    assert git(remote, "show", second.branch + ":instructions.md").stdout == "Second policy.\n"
    assert git(remote, "show", "main:instructions.md").stdout == "First policy.\n"


def test_non_fast_forward_race_is_recoverable(repository: Path, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Reject a concurrent remote writer rather than forcing main and allow a later reconciliation.

    Args:
        repository (Path): Synthetic Git checkout.
        tmp_path (Path): Independent worktrees.
        monkeypatch (MonkeyPatch): Inject one concurrent remote commit exactly before the final push.

    Returns:
        None: Both writers survive after an explicit retry.
    """
    sleeve = operations.start(repository, tmp_path / "sleeve", name="race")
    root = Path(sleeve.worktree)
    (root / "sleeve.md").write_text("Session work.\n")
    operations.checkpoint(root, ("sleeve.md",), "Record session work")
    original = git
    raced = False

    def race(cwd: Path, *arguments: str, allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
        """
        Advance main once at the publication boundary.

        Args:
            cwd (Path): Caller checkout.
            *arguments (str): Git operation.
            allowed (tuple[int, ...]): Accepted return codes.

        Returns:
            subprocess.CompletedProcess[str]: Real Git result after the injected concurrent write.
        """
        nonlocal raced
        if arguments == ("push", "origin", "HEAD:refs/heads/main") and not raced:
            raced = True
            (repository / "other.md").write_text("Concurrent work.\n")
            original(repository, "add", "other.md")
            original(repository, "-c", "commit.gpgsign=true", "commit", "-m", "Concurrent writer")
            original(repository, "push", "origin", "main")
        return original(cwd, *arguments, allowed=allowed)

    monkeypatch.setattr(operations, "git", race)
    with pytest.raises(SleeveError, match="Git failed"):
        operations.finish(root)
    assert state.current(root).closed_commit is None
    assert operations.finish(root).closed_commit is not None
    assert (root / "other.md").exists()


def test_dirty_and_post_closure_work_cannot_escape_guard(repository: Path, tmp_path: Path) -> None:
    """
    Preserve uncheckpointed work and reject new commits added to a previously closed session.

    Args:
        repository (Path): Synthetic Git checkout.
        tmp_path (Path): Sleeve directory.

    Returns:
        None: Closure is not a permanent bypass for later writes.
    """
    sleeve = operations.start(repository, tmp_path / "sleeve", name="guard")
    root = Path(sleeve.worktree)
    (root / "new.md").write_text("Keep this local change.\n")
    with pytest.raises(SleeveError, match="Checkpoint"):
        operations.finish(root)
    operations.checkpoint(root, ("new.md",), "Keep local change")
    operations.finish(root)
    (root / "new.md").write_text("Later work.\n")
    git(root, "add", "new.md")
    git(root, "-c", "commit.gpgsign=true", "commit", "-m", "Later work")
    with pytest.raises(SleeveError, match="after closure"):
        operations.guard(root)


def test_unrelated_staging_is_preserved(repository: Path, tmp_path: Path) -> None:
    """
    Keep selected checkpoint paths from silently including other staged work.

    Args:
        repository (Path): Synthetic checkout.
        tmp_path (Path): Sleeve directory.

    Returns:
        None: Unrelated staged contents remain untouched after the refusal.
    """
    sleeve = operations.start(repository, tmp_path / "sleeve", name="index")
    root = Path(sleeve.worktree)
    (root / "other.md").write_text("Unrelated.\n")
    (root / "chosen.md").write_text("Selected.\n")
    git(root, "add", "other.md")
    with pytest.raises(SleeveError, match="unrelated paths"):
        operations.checkpoint(root, ("chosen.md",), "Selected checkpoint")
    assert git(root, "diff", "--cached", "--name-only").stdout == "other.md\n"
