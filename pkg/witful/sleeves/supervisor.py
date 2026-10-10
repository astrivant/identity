"""
Drain a supervised workload on termination before bounded backup and reconciliation.
"""

from __future__ import annotations

import fcntl
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from witful.sleeves import state
from witful.sleeves.models import SleeveError

if TYPE_CHECKING:
    from types import FrameType


def _signal_group(pid: int, number: int) -> None:
    """
    Signal an owned process group, tolerating an already completed workload.

    Args:
        pid (int): Session leader created by this supervisor.
        number (int): POSIX signal to propagate.

    Returns:
        None: Existing group members receive the signal.
    """
    try:
        os.killpg(pid, number)
    except ProcessLookupError:
        pass


def _cleanup(repo: Path, arguments: list[str], deadline: float) -> bool:
    """
    Run a lifecycle command under the remaining shutdown budget without exposing its private output.

    Args:
        repo (Path): Current sleeve worktree.
        arguments (list[str]): Packaged lifecycle command and non-secret arguments.
        deadline (float): Absolute monotonic deadline shared by all cleanup operations.

    Returns:
        bool: Whether the lifecycle command completed successfully before the deadline.
    """
    remaining = deadline - time.monotonic()

    if remaining <= 0:
        return False

    with subprocess.Popen(
        [sys.executable, "-m", "witful.sleeves", *arguments, "--repo", str(repo)],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    ) as process:
        try:
            return process.wait(timeout=remaining) == 0
        except subprocess.TimeoutExpired:
            _signal_group(process.pid, signal.SIGKILL)
            process.wait()
            return False


def run(
    repo: Path,
    command: tuple[str, ...],
    *,
    paths: tuple[str, ...] = (),
    shutdown_seconds: float = 90,
    stop_seconds: float = 10,
    pull_request: bool = False,
) -> int:
    """
    Forward termination, stop writers, checkpoint, then reconcile without hiding interrupted work.

    Args:
        repo (Path): Open sleeve worktree.
        command (tuple[str, ...]): Workload executable and arguments; no shell interpretation.
        paths (tuple[str, ...]): Explicit plaintext checkpoint paths, empty for encrypted sources.
        shutdown_seconds (float): Total cleanup budget after termination or normal workload completion.
        stop_seconds (float): Maximum workload drain interval within the total budget.
        pull_request (bool): Require a review PR during reconciliation.

    Returns:
        int: Workload status on successful reconciliation, 128 plus a received signal, or two when closure fails.

    Raises:
        SleeveError: Another supervisor owns the sleeve, the receipt is closed, or timing is invalid.
    """
    if not command or not all(math.isfinite(value) for value in (shutdown_seconds, stop_seconds)):
        raise SleeveError("Provide a workload command and finite shutdown deadlines.")
    if not 0 < stop_seconds < shutdown_seconds:
        raise SleeveError("Require 0 < stop-seconds < shutdown-seconds.")

    sleeve = state.current(repo)

    if sleeve.closed_commit is not None:
        raise SleeveError("Start a new sleeve before supervising another instance.")
    if sleeve.keys is None and not paths:
        raise SleeveError("A plaintext sleeve needs --paths for its shutdown checkpoint.")

    with (Path(sleeve.directory) / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SleeveError("Another workload already owns this sleeve.") from None

        return _run(repo, command, paths, shutdown_seconds, stop_seconds, pull_request)


def _run(
    repo: Path,
    command: tuple[str, ...],
    paths: tuple[str, ...],
    shutdown_seconds: float,
    stop_seconds: float,
    pull_request: bool,
) -> int:
    """
    Own signal handlers only while the workload and bounded finalization are active.

    Args:
        repo (Path): Open sleeve worktree.
        command (tuple[str, ...]): Literal workload command.
        paths (tuple[str, ...]): Allowed checkpoint paths.
        shutdown_seconds (float): Total finalization budget.
        stop_seconds (float): Workload drain budget.
        pull_request (bool): Select review-gated integration.

    Returns:
        int: Observable workload, termination, or incomplete-reconciliation status.
    """
    child: subprocess.Popen[bytes] | None = None
    received = 0
    deadline: float | None = None
    stop_deadline: float | None = None

    def terminate(number: int, frame: FrameType | None) -> None:
        """
        Record the first stop request without performing Git or encryption in a signal handler.

        Args:
            number (int): Received termination signal.
            frame (FrameType | None): Interrupted frame, intentionally not inspected.

        Returns:
            None: Signal is forwarded once and deadlines cannot be extended by repeated signals.
        """
        nonlocal received, deadline, stop_deadline

        if not received:
            received = number
            now = time.monotonic()
            deadline = min(deadline, now + shutdown_seconds) if deadline is not None else now + shutdown_seconds
            stop_deadline = now + stop_seconds

            if child is not None:
                _signal_group(child.pid, number)

    previous = {number: signal.signal(number, terminate) for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}

    try:
        sleeve = state.current(repo)
        environment = dict(os.environ)
        environment["WITFUL_SLEEVE_WORKTREE"] = sleeve.worktree
        environment["WITFUL_SLEEVE_SOURCE"] = str(Path(sleeve.directory) / "source") if sleeve.keys else sleeve.worktree
        child = subprocess.Popen(command, cwd=repo, env=environment, start_new_session=True)

        if received:
            _signal_group(child.pid, received)

        while True:
            try:
                result = child.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if stop_deadline is not None and time.monotonic() >= stop_deadline:
                    _signal_group(child.pid, signal.SIGKILL)
                    result = child.wait()
                    break

        # No inherited-group writer may race the final snapshot after its leader exits.
        # Workloads must join their own children/threads; detached daemons are outside this contract.
        deadline = deadline if deadline is not None else time.monotonic() + shutdown_seconds
        drain_deadline = stop_deadline if stop_deadline is not None else time.monotonic() + stop_seconds
        _signal_group(child.pid, signal.SIGTERM)

        while time.monotonic() < drain_deadline:
            try:
                os.killpg(child.pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)

        _signal_group(child.pid, signal.SIGKILL)
        checkpoint = ["checkpoint", "--message", "Checkpoint supervised identity sleeve"]

        if paths:
            checkpoint.extend(["--paths", *paths])

        if not _cleanup(repo, checkpoint, deadline):
            _cleanup(repo, ["backup"], deadline)
            print("Sleeve checkpoint incomplete; last commits backed up when possible. Preserve its durable volume.", file=sys.stderr)
            return 2

        finish = ["finish", *(["--pull-request"] if pull_request else [])]

        if not _cleanup(repo, finish, deadline):
            print("Sleeve backed up but not reconciled. Resume finish from its durable worktree; session remains open.", file=sys.stderr)
            return 2

        return 128 + received if received else (128 - result if result < 0 else result)
    finally:
        if child is not None and child.poll() is None:
            _signal_group(child.pid, signal.SIGKILL)
            child.wait()

        for number, handler in previous.items():
            signal.signal(number, handler)
