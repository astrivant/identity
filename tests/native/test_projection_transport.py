"""
Verify actual Git remote CAS, independent fetch, lost acknowledgment recovery and parent-preserving publication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from witful.exceptions import NativeError
from witful.native.git import git
from witful.native.projection import transport
from witful.native.projection.bundle import prepare
from witful.native.projection.transport import GitRemote

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def test_remote_cas_and_lost_acknowledgment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Publish real objects, recover a lost push reply by fetching independently and reject a competing writer without rewriting it.

    Args:
        tmp_path (Path): Disposable remote and isolated gateway ciphertext directory.
        monkeypatch (pytest.MonkeyPatch): Lose exactly one acknowledgment after actual successful publication.

    Returns:
        None: Retries reuse exact bytes and external divergence preserves the remote's current history.
    """
    remote = tmp_path / "remote"
    remote.mkdir(mode=0o700)
    git(remote, ("init", "--bare", "--template=", "."))
    scratch = tmp_path / "gateway"
    scratch.mkdir(mode=0o700)
    destination = GitRemote(scratch, remote.as_uri(), "refs/heads/projection", {})
    first = prepare(b"synthetic-ciphertext-one", str(uuid4()), None, "Synthetic Export", "fixture@example.invalid", 100)
    first_oid = first.objects()[-1][1]
    observed: list[tuple[str, ...]] = []
    budgets: list[float] = []

    def lost_reply(
        directory: Path,
        arguments: tuple[str, ...],
        data: bytes | None = None,
        environment: Mapping[str, str] | None = None,
        limit: int = 64 * 1024 * 1024,
        lock_fd: int | None = None,
        seconds: float = 30.0,
    ) -> bytes:
        """
        Lose a single push acknowledgment after real Git completes; retain all independent verification calls.

        Args:
            directory (Path): Actual disposable Git repository.
            arguments (tuple[str, ...]): Original package-owned command.
            data (bytes | None): Exact synthetic object bytes.
            environment (Mapping[str, str] | None): Explicit transport environment.
            limit (int): Original output limit.
            lock_fd (int | None): Actual inherited process fence.
            seconds (float): Remaining complete transfer budget.

        Returns:
            bytes: Real command output except the one deliberately lost successful push reply.
        """
        result = git(directory, arguments, data, environment, limit, lock_fd, seconds)
        observed.append(arguments)
        budgets.append(seconds)
        if "push" in arguments and sum("push" in call for call in observed) == 1:
            raise NativeError("unknown")
        return result

    monkeypatch.setattr(transport, "git", lost_reply)
    with destination.lock() as descriptor:
        assert destination.publish(first, None, descriptor) == first_oid
        assert 0 < budgets[-1] < budgets[0] <= 30
        assert all(later <= earlier for earlier, later in zip(budgets, budgets[1:], strict=False))
        assert destination.publish(first, None, descriptor) == first_oid
    assert sum("push" in call for call in observed) == 1
    assert sum("fetch" in call for call in observed) >= 2
    second = prepare(b"synthetic-ciphertext-two", str(uuid4()), first_oid, "Synthetic Export", "fixture@example.invalid", 101)
    with destination.lock() as descriptor:
        second_oid = destination.publish(second, first_oid, descriptor)
        assert destination.readback(second, descriptor)
        with pytest.raises(NativeError, match="diverged"):
            destination.publish(first, None, descriptor)
        with pytest.raises(NativeError, match="invalid"):
            destination.publish(first, second_oid, descriptor)
    assert git(remote, ("rev-parse", "refs/heads/projection")).strip().decode() == second_oid
    assert git(remote, ("rev-list", "--parents", "-1", second_oid)).strip().decode().split() == [second_oid, first_oid]
    assert list(scratch.iterdir()) == [scratch / "delivery.lock"]
