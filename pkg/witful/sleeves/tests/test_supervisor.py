"""
Verify real signal delivery, final writes, and bounded shutdown cleanup without external services.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from witful.sleeves import operations, state, supervisor
from witful.sleeves.git import git

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.mark.parametrize("fixture_name", ["workload.py", "tree.py"])
@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_signal_drains_then_checkpoints_then_merges(
    repository: Path,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    number: int,
    fixture_name: str,
) -> None:
    """
    Wait for a real workload handshake before termination and include its final flushed write in main.

    Args:
        repository (Path): Synthetic Git checkout.
        tmp_path (Path): Isolated sleeve and readiness FIFO.
        monkeypatch (MonkeyPatch): Run lifecycle commands locally while retaining real Git and signal behavior.
        number (int): Signal propagated to the supervised workload.
        fixture_name (str): Single process or parent-and-child workload with a shared process group.

    Returns:
        None: Shutdown preserves the final write, closes the session, and retains signal exit status.
    """
    sleeve = operations.start(repository, tmp_path / "sleeve", name="signals")
    root = Path(sleeve.worktree)
    fifo = tmp_path / "ready"
    os.mkfifo(fifo)
    order: list[str] = []
    previous = signal.getsignal(number)
    paths = ("final.md", "joined.md") if fixture_name == "tree.py" else ("final.md",)

    def cleanup(repo: Path, arguments: list[str], deadline: float) -> bool:
        """
        Exercise actual lifecycle operations after the child has stopped writing.

        Args:
            repo (Path): Sleeve checkout.
            arguments (list[str]): Requested lifecycle operation.
            deadline (float): Absolute finalization deadline.

        Returns:
            bool: Whether the requested operation completed in this deterministic fixture.
        """
        assert deadline > time.monotonic()
        assert (repo / "final.md").read_text() == "Flushed after signal.\n"
        if fixture_name == "tree.py":
            assert (repo / "joined.md").read_text() == "Child joined before snapshot.\n"

        order.append(arguments[0])
        if arguments[0] == "checkpoint":
            operations.checkpoint(repo, paths, "Capture drained work")
        else:
            operations.finish(repo)
        return True

    def terminate_when_ready() -> None:
        """
        Deliver the signal only after the workload installed its handler.

        Returns:
            None: The parent's active supervisor receives the selected signal.
        """
        with fifo.open() as stream:
            assert stream.read() == "ready"
        os.kill(os.getpid(), number)

    monkeypatch.setattr(supervisor, "_cleanup", cleanup)
    sender = threading.Thread(target=terminate_when_ready, daemon=True)
    sender.start()
    fixture = Path(__file__).parent / "fixtures" / fixture_name
    result = supervisor.run(root, (sys.executable, str(fixture), str(fifo)), paths=paths, shutdown_seconds=20, stop_seconds=2)
    sender.join(timeout=3)
    assert not sender.is_alive()
    assert result == 128 + number
    assert order == ["checkpoint", "finish"]
    assert signal.getsignal(number) == previous
    assert state.current(root).closed_commit is not None
    remote = Path(git(repository, "remote", "get-url", "origin").stdout.strip())
    assert git(remote, "show", "main:final.md").stdout == "Flushed after signal.\n"

    if fixture_name == "tree.py":
        assert git(remote, "show", "main:joined.md").stdout == "Child joined before snapshot.\n"


def test_cleanup_timeout_kills_and_reaps_child(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Bound a stalled finalization subprocess and collect it before returning failure.

    Args:
        tmp_path (Path): Private process working directory.
        monkeypatch (MonkeyPatch): Substitute a deliberately blocked local process for Git/network cleanup.

    Returns:
        None: Cleanup cannot exceed its deadline indefinitely or leave its direct child running.
    """
    actual = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def blocked(arguments: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        """
        Launch a real blocked process with the cleanup process-group contract.

        Args:
            arguments (list[str]): Original lifecycle arguments, intentionally unused by this fixture.
            **kwargs (object): Original launch options, replaced with explicit test-safe options.

        Returns:
            subprocess.Popen[bytes]: Child waiting indefinitely for a signal.
        """
        child = actual([sys.executable, str(Path(__file__).parent / "fixtures/blocked.py")], start_new_session=True)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", blocked)
    assert not supervisor._cleanup(tmp_path, ["finish"], time.monotonic() + 0.2)
    assert children[0].poll() == -signal.SIGKILL


def test_failed_checkpoint_still_attempts_committed_backup(repository: Path, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Preserve existing commits when a partial source edit cannot be safely committed on shutdown.

    Args:
        repository (Path): Synthetic Git checkout.
        tmp_path (Path): Sleeve directory.
        monkeypatch (MonkeyPatch): Deterministic failing lifecycle boundary.

    Returns:
        None: Backup follows a failed checkpoint, reconciliation is skipped, and the sleeve remains open.
    """
    sleeve = operations.start(repository, tmp_path / "sleeve", name="failed")
    root = Path(sleeve.worktree)
    order: list[str] = []

    def fail_checkpoint(repo: Path, arguments: list[str], deadline: float) -> bool:
        """
        Fail validation while recording which recovery operations were attempted.

        Args:
            repo (Path): Sleeve worktree.
            arguments (list[str]): Requested lifecycle operation.
            deadline (float): Absolute shared deadline.

        Returns:
            bool: Only a backup is successful in this fixture.
        """
        order.append(arguments[0])
        return arguments[0] == "backup"

    monkeypatch.setattr(supervisor, "_cleanup", fail_checkpoint)
    fixture = Path(__file__).parent / "fixtures/exit.py"
    assert supervisor.run(root, (sys.executable, str(fixture)), paths=("instructions.md",)) == 2
    assert order == ["checkpoint", "backup"]
    assert state.current(root).closed_commit is None
