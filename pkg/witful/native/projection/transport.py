"""
Publish an exact encrypted candidate through Git's compare-and-set protocol and independently fetch its bytes before acknowledgment.
"""

from __future__ import annotations

import fcntl
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from attrs import frozen

from witful.exceptions import NativeError
from witful.native.git import git

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from witful.native.projection.bundle import Bundle


@frozen
class GitRemote:
    """
    Own one configured remote/ref and inherited process fencing, with remote credentials isolated from the native controller.

    Attributes:
        directory (Path): Gateway-owned protected ciphertext scratch and lock directory on a bounded filesystem.
        remote (str): Operator-selected remote URL; request payloads cannot choose it.
        ref (str): Exact operator-selected branch ref, never a wildcard, deletion or refspec expression.
        environment (Mapping[str, str]): Explicit reviewed Git transport configuration; secret values stay in mounted files.
        max_bytes (int): Candidate and returned-object bound; deployment storage quota also bounds fetched packfiles.
    """

    directory: Path
    remote: str
    ref: str
    environment: Mapping[str, str]
    max_bytes: int = 64 * 1024 * 1024

    def __attrs_post_init__(self) -> None:
        """
        Require an existing private gateway workspace and one explicit branch ref before accepting any request.

        Returns:
            None: Local ownership and ref syntax are valid; production URL and credential policy is checked by configuration.
        """
        status = self.directory.lstat()
        if not self.directory.is_dir() or self.directory.is_symlink() or status.st_uid != os.getuid() or status.st_mode & 0o077:
            raise NativeError("denied")
        if not self.ref.startswith("refs/heads/") or not self.remote or self.remote.startswith("-") or self.max_bytes < 1:
            raise NativeError("invalid")
        git(self.directory, ("check-ref-format", self.ref), environment=self.environment)

    @contextmanager
    def lock(self) -> Iterator[int]:
        """
        Keep one process owner, with the lock inherited by Git children so parent death cannot release an active local transfer.

        Yields:
            int: Lock descriptor inherited by every Git child until bounded completion or termination.
        """
        descriptor = os.open(self.directory / "delivery.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            status = os.fstat(descriptor)
            if not stat.S_ISREG(status.st_mode) or status.st_uid != os.getuid() or status.st_mode & 0o077:
                raise NativeError("denied")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise NativeError("unavailable") from None
            yield descriptor
        finally:
            # Closing our descriptor preserves the child's inherited lock after abrupt parent loss.
            os.close(descriptor)

    def command(
        self,
        directory: Path,
        arguments: tuple[str, ...],
        descriptor: int,
        deadline: float,
        data: bytes | None = None,
        limit: int | None = None,
    ) -> bytes:
        """
        Share one complete-operation deadline across every Git subprocess, including lost-acknowledgment verification.

        Args:
            directory (Path): Isolated current object database.
            arguments (tuple[str, ...]): Package-owned exact Git command.
            descriptor (int): Inherited current gateway fence.
            deadline (float): Complete operation's monotonic deadline.
            data (bytes | None): Exact optional object bytes.
            limit (int | None): Optional tighter returned-byte limit.

        Returns:
            bytes: Bounded real Git output; an exhausted operation cannot admit another child process.
        """
        return git(
            directory,
            arguments,
            data=data,
            environment=self.environment,
            limit=min(self.max_bytes, limit) if limit is not None else self.max_bytes,
            lock_fd=descriptor,
            seconds=deadline - time.monotonic(),
        )

    def head(self, directory: Path, descriptor: int, deadline: float) -> str | None:
        """
        Read the exact advertised branch, distinguishing absent state from transport uncertainty.

        Args:
            directory (Path): Disposable isolated Git repository.
            descriptor (int): Current inherited gateway fence.
            deadline (float): Shared monotonic completion deadline for the whole transfer/readback.

        Returns:
            str | None: Exact remote OID, or no matching ref after a successful advertisement.
        """
        raw = self.command(
            directory, ("ls-remote", "--refs", "--", self.remote, self.ref), limit=4096, descriptor=descriptor, deadline=deadline
        )
        if not raw:
            return None
        try:
            oid, ref = raw.decode("ascii").strip().split("\t")
        except (UnicodeError, ValueError):
            raise NativeError("invalid") from None
        if ref != self.ref or len(oid) != 40 or any(char not in "0123456789abcdef" for char in oid):
            raise NativeError("invalid")
        return oid

    def readback(self, bundle: Bundle, descriptor: int, deadline: float | None = None) -> bool:
        """
        Fetch into a fresh object database, then compare exact commit/tree/blob bytes independently of the upload workspace.

        Args:
            bundle (Bundle): Exact prepared and authorized candidate.
            descriptor (int): Current inherited gateway fence.
            deadline (float | None): Shared monotonic completion deadline for the whole transfer/readback.

        Returns:
            bool: Whether the remote branch exposes exactly this independently retrieved candidate.
        """
        deadline = time.monotonic() + 30 if deadline is None else deadline
        with TemporaryDirectory(prefix="verify-", dir=self.directory) as temporary:
            directory = Path(temporary)
            self.command(directory, ("init", "--bare", "."), descriptor=descriptor, deadline=deadline)
            oid = bundle.objects()[-1][1]
            if self.head(directory, descriptor, deadline) != oid:
                return False
            self.command(
                directory,
                (
                    "-c",
                    "fetch.fsckObjects=true",
                    "fetch",
                    "--no-tags",
                    "--depth=2",
                    "--no-write-fetch-head",
                    self.remote,
                    f"{self.ref}:refs/heads/verify",
                ),
                limit=self.max_bytes,
                descriptor=descriptor,
                deadline=deadline,
            )
            fetched = self.command(directory, ("rev-parse", "refs/heads/verify"), descriptor=descriptor, deadline=deadline).strip()
            if fetched != oid.encode("ascii"):
                return False
            for kind, expected, payload in bundle.objects():
                actual = self.command(
                    directory, ("cat-file", kind, expected), limit=self.max_bytes, descriptor=descriptor, deadline=deadline
                )
                if actual != payload:
                    raise NativeError("invalid")
            # Recheck the advertised ref after object retrieval; a concurrent external writer is never silently adopted.
            return self.head(directory, descriptor, deadline) == oid

    def publish(self, bundle: Bundle, expected: str | None, descriptor: int, deadline: float | None = None) -> str:
        """
        Perform only a parent-preserving expected-old update, resolving lost acknowledgments through independent readback.

        Args:
            bundle (Bundle): Exact independently verified candidate, including its approved parent.
            expected (str | None): Durable expected remote head or explicit absent-ref boundary.
            descriptor (int): Current gateway lock, inherited by the transfer process.
            deadline (float | None): Shared monotonic transfer deadline; standalone callers default to thirty seconds.

        Returns:
            str: Exact verified remote commit OID; uncertainty and divergence remain distinct failures.
        """
        deadline = time.monotonic() + 30 if deadline is None else deadline
        parents = tuple(line[7:] for line in bundle.commit.split(b"\n\n", 1)[0].splitlines() if line.startswith(b"parent "))
        if parents != ((expected.encode("ascii"),) if expected is not None else ()):
            raise NativeError("invalid")
        oid = bundle.objects()[-1][1]
        with TemporaryDirectory(prefix="upload-", dir=self.directory) as temporary:
            directory = Path(temporary)
            self.command(directory, ("init", "--bare", "."), descriptor=descriptor, deadline=deadline)
            current = self.head(directory, descriptor, deadline)
            if current == oid:
                if self.readback(bundle, descriptor, deadline):
                    return oid
                raise NativeError("unknown")
            if current != expected:
                raise NativeError("diverged")
            if expected is not None:
                self.command(
                    directory,
                    ("fetch", "--no-tags", "--no-write-fetch-head", self.remote, f"{self.ref}:refs/heads/base"),
                    limit=self.max_bytes,
                    descriptor=descriptor,
                    deadline=deadline,
                )
                actual = self.command(directory, ("rev-parse", "refs/heads/base"), descriptor=descriptor, deadline=deadline).strip()
                if actual != expected.encode("ascii"):
                    raise NativeError("diverged")
            for kind, wanted, payload in bundle.objects():
                actual = self.command(
                    directory,
                    ("hash-object", "-t", kind, "-w", "--stdin"),
                    data=payload,
                    limit=self.max_bytes,
                    descriptor=descriptor,
                    deadline=deadline,
                ).strip()
                if actual != wanted.encode("ascii"):
                    raise NativeError("invalid")
            # The exact lease supplies CAS, while the previously verified commit parent prohibits a history rewrite.
            try:
                self.command(
                    directory,
                    (
                        "-c",
                        "push.followTags=false",
                        "push",
                        "--porcelain",
                        f"--force-with-lease={self.ref}:{expected or ''}",
                        "--",
                        self.remote,
                        f"{oid}:{self.ref}",
                    ),
                    limit=self.max_bytes,
                    descriptor=descriptor,
                    deadline=deadline,
                )
            except NativeError as error:
                if error.code != "unknown":
                    raise
                # A lost acknowledgment does not authorize new bytes or imply the remote rejected the original candidate.
                if self.readback(bundle, descriptor, deadline):
                    return oid
                raise NativeError("unknown") from None
            if not self.readback(bundle, descriptor, deadline):
                raise NativeError("unknown")
            return oid
