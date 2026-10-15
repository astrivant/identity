"""
Use one fsynced Git root ref as the atomic publication boundary for ciphertext-only native storage.
"""

from __future__ import annotations

import fcntl
import os
import selectors
import signal
import subprocess
import time
from contextlib import contextmanager
from threading import Event
from typing import TYPE_CHECKING

from attrs import field, frozen

from witful.exceptions import NativeError
from witful.native import codec
from witful.native.context import identifier
from witful.native.postgres import binding
from witful.native.storage import Batch, Head, Object, Scope
from witful.native.wire import decode_batch, encode_batch

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

__all__ = ["Git", "git"]


def git(
    directory: Path,
    arguments: tuple[str, ...],
    data: bytes | None = None,
    environment: Mapping[str, str] | None = None,
    limit: int = 64 * 1024 * 1024,
    lock_fd: int | None = None,
) -> bytes:
    """
    Execute local Git plumbing with bounded time and redacted diagnostics.

    Args:
        directory (Path): Existing repository or protected parent for explicit initialization.
        arguments (tuple[str, ...]): Package-owned plumbing arguments, without shell evaluation.
        data (bytes | None): Binary stdin, never logged.
        environment (Mapping[str, str] | None): Explicit exporter identity and time when creating new commits.
        limit (int): Maximum returned binary bytes.
        lock_fd (int | None): Recovery lock inherited by a ref-mutating child, retaining fencing after parent loss.

    Returns:
        bytes: Successful Git output; process diagnostics are never reflected.
    """
    if limit < 1 or (data is not None and len(data) > limit):
        raise NativeError("incomplete")
    pending = memoryview(data or b"")
    output = bytearray()
    deadline = time.monotonic() + 30
    try:
        with subprocess.Popen(
            ["git", "-c", "core.fsync=all", "-c", "core.fsyncMethod=fsync", "-c", "gc.auto=0", *arguments],
            cwd=directory,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            # Ignore ambient Git routing, injected config and trace destinations. Only this call may select Git-specific settings.
            env={
                **{name: value for name, value in os.environ.items() if not name.startswith("GIT_")},
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                **(environment or {}),
            },
            start_new_session=True,
            pass_fds=(lock_fd,) if lock_fd is not None else (),
            bufsize=0,
        ) as process:
            assert process.stdin is not None and process.stdout is not None
            try:
                with selectors.DefaultSelector() as selector:
                    os.set_blocking(process.stdout.fileno(), False)
                    os.set_blocking(process.stdin.fileno(), False)
                    selector.register(process.stdout, selectors.EVENT_READ, "output")
                    if pending:
                        selector.register(process.stdin, selectors.EVENT_WRITE, "input")
                    else:
                        process.stdin.close()
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise NativeError("unknown")
                        for key, _ in selector.select(remaining):
                            if key.data == "input":
                                written = os.write(key.fd, pending[:65536])
                                pending = pending[written:]
                                if not pending:
                                    selector.unregister(key.fd)
                                    process.stdin.close()
                            else:
                                chunk = os.read(key.fd, min(65536, limit + 1 - len(output)))
                                if not chunk:
                                    selector.unregister(key.fd)
                                output.extend(chunk)
                                if len(output) > limit:
                                    raise NativeError("incomplete")
                    if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
                        raise NativeError("unknown")
            finally:
                # Own the entire Git/helper process group; no abandoned transfer survives a timeout or byte-budget refusal.
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    except (OSError, subprocess.TimeoutExpired):
        raise NativeError("unknown") from None
    return bytes(output)


@frozen
class Git:
    """
    Retain encrypted transaction ancestry under a single CAS ref; arbitrary Git readers receive no multi-ref snapshot promise.

    Attributes:
        directory (Path): Existing protected bare repository with deployment-owned single-writer volume fencing.
        author (str): Honest exporter identity for newly created storage commits.
        email (str): Exporter contact, not an imported historical author.
        max_objects (int): Maximum complete retained transactions or objects per bounded operation.
        max_bytes (int): Maximum aggregate transfer bytes.
    """

    directory: Path = field(repr=False)
    author: str
    email: str
    max_objects: int = 4096
    max_bytes: int = 64 * 1024 * 1024

    def ref(self, scope: Scope) -> str:
        """
        Derive a safe opaque publication ref from validated routing UUIDs.

        Args:
            scope (Scope): Authorized identity partition.

        Returns:
            str: Sole native root ref for this identity.
        """
        return f"refs/witful/{scope.tenant}/{scope.identity}"

    def oid(self, scope: Scope) -> str | None:
        """
        Read one complete root selection without resolving user-controlled ref expressions.

        Args:
            scope (Scope): Authorized partition.

        Returns:
            str | None: Current Git commit OID or an absent partition.
        """
        data = git(self.directory, ("for-each-ref", "--format=%(objectname) %(refname)", self.ref(scope)))
        matches = [line.split()[0] for line in data.decode("ascii").splitlines() if line.split()[1] == self.ref(scope)]
        if len(matches) > 1:
            raise NativeError("invalid")
        return matches[0] if matches else None

    def batch(self, oid: str) -> Batch:
        """
        Read the exact prepared transaction stored in a commit.

        Args:
            oid (str): Internally resolved Git commit ID.

        Returns:
            Batch: Complete immutable ciphertext candidate.
        """
        payload = git(self.directory, ("show", f"{oid}:transaction"), limit=self.max_bytes)
        return decode_batch(payload, codec.Limits(bytes=self.max_bytes, items=self.max_objects * 32))

    def head(self, scope: Scope) -> Head:
        """
        Read the frontier selected by the sole native root ref.

        Args:
            scope (Scope): Authorized partition.

        Returns:
            Head: Complete native frontier.
        """
        current = self.oid(scope)
        return self.batch(current).target if current is not None else Head()

    def get(self, scope: Scope, identifiers: tuple[str, ...]) -> tuple[Object, ...]:
        """
        Fetch exact immutable ciphertext paths from one selected Git commit.

        Args:
            scope (Scope): Authorized partition.
            identifiers (tuple[str, ...]): Independently authorized opaque object UUIDs.

        Returns:
            tuple[Object, ...]: Complete bounded ciphertext result in requested order.
        """
        if len(identifiers) > self.max_objects:
            raise NativeError("incomplete")
        current = self.oid(scope)
        if current is None:
            raise NativeError("incomplete")
        result: list[Object] = []
        size = 0
        for value in identifiers:
            identifier(value)
            payload = git(self.directory, ("show", f"{current}:objects/{value}"), limit=self.max_bytes - size)
            size += len(payload)
            result.append(Object(value, payload))
        return tuple(result)

    def history(self, scope: Scope) -> tuple[Batch, ...]:
        """
        Export complete retained transaction ancestry without silently truncating history.

        Args:
            scope (Scope): Authorized partition.

        Returns:
            tuple[Batch, ...]: Exact encrypted transactions in native commit order.
        """
        current = self.oid(scope)
        if current is None:
            return ()
        history = git(self.directory, ("rev-list", "--first-parent", "--reverse", f"--max-count={self.max_objects + 1}", current))
        oids = history.decode("ascii").splitlines()
        if len(oids) > self.max_objects:
            raise NativeError("incomplete")
        result: list[Batch] = []
        size = 0
        for oid in oids:
            batch = self.batch(oid)
            size += sum(len(item.payload) for item in (batch.root, batch.receipt, *batch.objects, *batch.outbox))
            if size > self.max_bytes:
                raise NativeError("incomplete")
            if batch.expected != (result[-1].target if result else Head()):
                raise NativeError("invalid")
            result.append(batch)
        return tuple(result)

    def receipt(self, scope: Scope, operation: str) -> Object | None:
        """
        Find an original durable receipt without creating another semantic write.

        Args:
            scope (Scope): Authorized partition.
            operation (str): Stable caller operation UUID.

        Returns:
            Object | None: Original encrypted receipt or no observed commit.
        """
        identifier(operation)
        return next((batch.receipt for batch in self.history(scope) if batch.operation == operation), None)

    @contextmanager
    def lock(self, scope: Scope) -> Iterator[int]:
        """
        Serialize local write settlement with a lock that the ref-mutating child also owns.

        Args:
            scope (Scope): Current identity partition.

        Yields:
            int: Locked descriptor inherited by the mutating Git process, preventing premature recovery after parent death.
        """
        descriptor = os.open(self.directory / f"native-{scope.tenant}-{scope.identity}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        deadline = time.monotonic() + 30
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise NativeError("unknown") from None
                    Event().wait(0.02)
            yield descriptor
        finally:
            os.close(descriptor)

    def resolve(self, scope: Scope, operation: str) -> tuple[Head, Object | None]:
        """
        Wait for a surviving ref writer before classifying an uncertain commit.

        Args:
            scope (Scope): Current recovery scope.
            operation (str): Prepared operation UUID.

        Returns:
            tuple[Head, Object | None]: Settled frontier and original receipt under one local lock.
        """
        with self.lock(scope):
            return self.head(scope), self.receipt(scope, operation)

    def commit(self, scope: Scope, batch: Batch) -> Head:
        """
        Hold an inherited recovery fence across all local publication work.

        Args:
            scope (Scope): Current externally fenced scope.
            batch (Batch): Exact prepared candidate.

        Returns:
            Head: Durable target after a settled ref update.
        """
        with self.lock(scope) as descriptor:
            return self._commit(scope, batch, descriptor)

    def _commit(self, scope: Scope, batch: Batch, descriptor: int) -> Head:
        """
        Write immutable encrypted objects, fsync Git storage and publish one expected-old root ref.

        Args:
            scope (Scope): Current externally fenced identity scope.
            batch (Batch): Exact prepared candidate, sealed before entering the authority lock.

            descriptor (int): Held recovery lock inherited by the ref-mutating Git child.

        Returns:
            Head: Durable target; uncertain ref update remains unknown until independent readback.
        """
        current = self.oid(scope)
        history = self.history(scope)
        prior = next((item for item in history if item.operation == batch.operation), None)
        if prior is not None:
            if binding(prior) != binding(batch):
                raise NativeError("conflict")
            return prior.target
        if (history[-1].target if history else Head()) != batch.expected:
            raise NativeError("conflict")
        objects: dict[str, bytes] = {}
        for item in (*history, batch):
            for stored in (item.root, item.receipt, *item.objects, *item.outbox):
                if stored.id in objects and objects[stored.id] != stored.payload:
                    raise NativeError("conflict")
                objects[stored.id] = stored.payload
        if len(objects) > self.max_objects or sum(map(len, objects.values())) > self.max_bytes:
            raise NativeError("incomplete")
        entries: list[bytes] = []
        for name, payload in sorted(objects.items()):
            oid = git(self.directory, ("hash-object", "-w", "--stdin"), payload).strip()
            entries.append(b"100644 blob " + oid + b"\t" + name.encode("ascii") + b"\0")
        tree = git(self.directory, ("mktree", "-z"), b"".join(entries)).strip()
        transaction = encode_batch(batch, codec.Limits(bytes=self.max_bytes, items=self.max_objects * 32))
        transaction_oid = git(self.directory, ("hash-object", "-w", "--stdin"), transaction).strip()
        root = (
            git(
                self.directory,
                ("mktree", "-z"),
                b"040000 tree " + tree + b"\tobjects\0" + b"100644 blob " + transaction_oid + b"\ttransaction\0",
            )
            .strip()
            .decode("ascii")
        )
        environment = {
            "GIT_AUTHOR_NAME": self.author,
            "GIT_AUTHOR_EMAIL": self.email,
            "GIT_COMMITTER_NAME": self.author,
            "GIT_COMMITTER_EMAIL": self.email,
        }
        parent = ("-p", current) if current is not None else ()
        commit = (
            git(self.directory, ("commit-tree", root, *parent), b"Commit encrypted native transaction\n", environment)
            .strip()
            .decode("ascii")
        )
        # Empty expected-old is the documented create-if-absent contract for either Git object hash format.
        git(self.directory, ("update-ref", self.ref(scope), commit, current or ""), lock_fd=descriptor)
        return batch.target
