"""
Load reviewed sources and fingerprint explicit Git workspaces without storing file contents.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

from witful.completion.models import Workspace
from witful.knowledge.compiler import compile_identity
from witful.knowledge.contracts import structure
from witful.knowledge.models import Catalog, Identity
from witful.lessons import read_journal


def identity(root: Path) -> Identity:
    """
    Compile only the selected collection's maintained teaching sources.

    Args:
        root (Path): Explicit collection root, never discovered from other identities.

    Returns:
        Identity: Validated current tree, including sourced Insights and retained history.
    """
    return compile_identity(
        read_journal(root / "lessons.jsonl"), structure(json.loads((root / "knowledge/catalog.json").read_text()), Catalog)
    )


def git(root: Path, *arguments: str) -> bytes:
    """
    Run a bounded read-only Git operation without shell interpolation or optional index writes.

    Args:
        root (Path): Explicit working directory.
        *arguments (str): Individually delimited Git arguments.

    Returns:
        bytes: Successful command output; stderr remains out of hook responses.
    """
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        timeout=20,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    ).stdout


def snapshot(root: Path) -> Workspace:
    """
    Hash the checkout's committed identity, index, and current owned files, including nonignored additions.

    Args:
        root (Path): Explicit directory inside a Git checkout.

    Returns:
        Workspace: Private local path and content digests; no file bytes are retained.

    Raises:
        ValueError: A file exceeds 32 MiB, a path escapes the checkout, or an unsupported file type occurs.
        RuntimeError: Git metadata changes while files are read.
    """
    root = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip()).resolve()
    head = git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    staged = git(root, "ls-files", "--stage", "-z")
    names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    digest = hashlib.sha256(staged)

    # Git supplies the allowlist. Symlink targets are hashed as links and are never followed outside the checkout.
    for raw in sorted(set(names.split(b"\0")) - {b""}):
        relative = Path(os.fsdecode(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Git returned a path outside the workspace")
        if relative.parts[:2] == (".witful", "completion"):
            continue
        path = root / relative
        digest.update(raw + b"\0")
        try:
            info = path.lstat()
        except FileNotFoundError:
            digest.update(b"missing\0")
            continue
        if not path.parent.resolve().is_relative_to(root):
            raise ValueError("A workspace parent path escapes through a symlink")
        digest.update(str(stat.S_IMODE(info.st_mode)).encode() + b"\0")
        if stat.S_ISLNK(info.st_mode):
            content = os.fsencode(os.readlink(path))
        elif stat.S_ISREG(info.st_mode) and info.st_size <= 32 * 1024 * 1024:
            content = path.read_bytes()
        else:
            raise ValueError("Workspace contains an unsupported file or a file larger than 32 MiB")
        digest.update(hashlib.sha256(content).digest())
    if (
        staged != git(root, "ls-files", "--stage", "-z")
        or names != git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
        or head != git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    ):
        raise RuntimeError("Workspace Git metadata changed during review capture")
    return Workspace(str(root), head, digest.hexdigest())


def snapshots(roots: tuple[Path, ...]) -> tuple[Workspace, ...]:
    """
    Capture distinct caller-selected checkouts in a stable order.

    Args:
        roots (tuple[Path, ...]): Explicit selected workspaces, potentially repeated through subdirectories.

    Returns:
        tuple[Workspace, ...]: Sorted unique checkout snapshots.
    """
    selected = {os.fsdecode(git(root, "rev-parse", "--show-toplevel")).strip() for root in roots}
    result = {item.path: item for item in (snapshot(Path(path)) for path in sorted(selected))}
    return tuple(result[key] for key in sorted(result))


def context_workspaces(root: Path, cwd: Path) -> tuple[Path, ...]:
    """
    Select the collection and an existing Git workspace without hashing unrelated non-Git directories.

    Args:
        root (Path): Required collection checkout.
        cwd (Path): Native hook working directory, which can represent a conversation without code changes.

    Returns:
        tuple[Path, ...]: Explicit existing checkouts; non-Git outputs require manual evidence references.

    Raises:
        ValueError: The hook working directory is missing.
    """
    if not cwd.is_dir():
        raise ValueError("The hook working directory does not exist")
    for directory in (cwd, *cwd.parents):
        if (directory / ".git").exists():
            return (root, cwd)
    return (root,)


def runtime_directory(root: Path) -> Path:
    """
    Create private ignored review state without following symlinks out of the owning collection.

    Args:
        root (Path): Explicit resolved collection root.

    Returns:
        Path: Private local audit directory.

    Raises:
        ValueError: Runtime paths are symlinks or the audit directory is not ignored by Git.
    """
    directory = root / ".witful/completion"
    for path in (directory.parent, directory):
        if path.is_symlink():
            raise ValueError("Completion state directories must not be symlinks")
    git(root, "check-ignore", "--quiet", str(directory / "probe.json"))
    for path in (directory.parent, directory):
        path.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    return directory
