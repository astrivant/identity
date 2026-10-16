"""
Capture approved clean Git snapshots without executing repository hooks, filters or instructions.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
from pathlib import Path

from attrs import frozen

from witful.codegraph.models import Enrollment, File, Source, digest, relative
from witful.exceptions import NativeError
from witful.native.git import git as native_git


@frozen
class Snapshot:
    """
    Carry immutable build inputs independently of SDK working files.

    Attributes:
        revision (str): Exact checked-out commit.
        tree (str): Committed tree ID.
        sources (tuple[Source, ...]): Approved Python source bytes decoded as UTF-8.
        files (tuple[File, ...]): Complete tracked coverage inventory.
        untracked (bool): Whether untracked files were visibly omitted.
    """

    revision: str
    tree: str
    sources: tuple[Source, ...]
    files: tuple[File, ...]
    untracked: bool


def git(root: Path, arguments: tuple[str, ...], limit: int) -> bytes:
    """
    Read repository metadata with a bounded process and a closed environment.

    Args:
        root (Path): Approved existing workspace.
        arguments (tuple[str, ...]): Package-owned Git arguments.
        limit (int): Maximum admitted response size.

    Returns:
        bytes: Successful bounded metadata or exact committed blob bytes.
    """
    environment = {
        "PATH": os.defpath,
        "HOME": str(root),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
    }
    return native_git(
        root,
        ("--no-pager", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *arguments),
        environment=environment,
        limit=limit,
        seconds=15,
    )


def read_source(root: Path, path: str, size: int) -> bytes:
    """
    Open every source component without following symlinks, including concurrent replacements.

    Args:
        root (Path): Canonical enrolled workspace.
        path (str): Validated relative path.
        size (int): Maximum exact committed file size.

    Returns:
        bytes: Bounded regular-file bytes; aliases and special files fail closed.
    """
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = path.split("/")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        source = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(source, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise NativeError("denied")
            return stream.read(size + 1)
    finally:
        os.close(descriptor)


def capture(enrollment: Enrollment, revision: str) -> Snapshot:
    """
    Admit only a canonical clean tracked snapshot and expose exclusions explicitly.

    Args:
        enrollment (Enrollment): Independently approved root, filters and resource limits.
        revision (str): Exact requested current commit.

    Returns:
        Snapshot: Immutable indexed input; submodules, symlinks and dirty tracked files fail closed.
    """
    if not digest(revision, (40, 64)):
        raise NativeError("invalid")
    root = Path(enrollment.repository)
    try:
        if str(root.resolve(strict=True)) != enrollment.repository:
            raise NativeError("denied")
        if git(root, ("rev-parse", "--show-toplevel"), 4096).decode().strip() != str(root):
            raise NativeError("denied")
        if git(root, ("rev-parse", "HEAD"), 128).decode().strip() != revision:
            raise NativeError("conflict")
        # Cached comparisons never run working-tree clean filters or external diff programs.
        if git(root, ("diff-index", "--cached", "--raw", "--no-ext-diff", "--no-textconv", revision, "--"), 1024):
            raise NativeError("conflict")
        tree = git(root, ("rev-parse", revision + "^{tree}"), 128).decode().strip()
        entries = git(root, ("ls-tree", "-rz", "-l", "--full-tree", revision), enrollment.files * 8192).split(b"\0")[:-1]
        if len(entries) > enrollment.files:
            raise NativeError("incomplete")
        sources: list[Source] = []
        files: list[File] = []
        total = 0
        for entry in entries:
            metadata, encoded_path = entry.split(b"\t", 1)
            mode, kind, blob, length = metadata.decode().split()
            path = relative(encoded_path.decode("utf-8"))
            if mode not in {"100644", "100755"} or kind != "blob":
                raise NativeError("denied")
            location = root / path
            if location.is_symlink() or location.resolve(strict=True) != location:
                raise NativeError("denied")
            for parent in location.parents:
                if parent == root:
                    break
                if (parent / ".git").exists():
                    raise NativeError("denied")
            # Verify all tracked bytes, including excluded files, without Git attributes/filter execution.
            size = int(length)
            total += size
            if total > enrollment.source_bytes:
                raise NativeError("incomplete")
            raw = read_source(root, path, size)
            algorithm = "sha1" if len(blob) == 40 else "sha256"
            committed = hashlib.new(algorithm, f"blob {size}\0".encode() + raw).hexdigest()
            if len(raw) != size or committed != blob:
                raise NativeError("conflict")
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in enrollment.excluded):
                files.append(File(path, blob, "excluded"))
            elif not path.endswith(".py"):
                files.append(File(path, blob, "unsupported"))
            else:
                hashed = hashlib.sha256(raw).hexdigest()
                sources.append(Source(path, raw.decode("utf-8"), hashed))
                files.append(File(path, hashed, "indexed"))
        untracked = bool(git(root, ("ls-files", "--others", "--exclude-standard", "-z"), enrollment.files * 8192))
        if git(root, ("rev-parse", "HEAD"), 128).decode().strip() != revision:
            raise NativeError("conflict")
        return Snapshot(revision, tree, tuple(sources), tuple(files), untracked)
    except (OSError, ValueError):
        raise NativeError("invalid") from None
