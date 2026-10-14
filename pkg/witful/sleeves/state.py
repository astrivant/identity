"""
Keep private session receipts and serialize local lifecycle commands across worktrees.
"""

from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from witful.exceptions import SleeveError
from witful.files import replace_file
from witful.knowledge.contracts import as_data, structure
from witful.sleeves.git import git
from witful.sleeves.models import Sleeve

if TYPE_CHECKING:
    from collections.abc import Iterator


def registry(repo: Path) -> Path:
    """
    Locate private receipts shared by linked worktrees without adding them to Git.

    Args:
        repo (Path): Existing repository or linked worktree.

    Returns:
        Path: Owner-only metadata directory under Git's common directory.
    """
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    path = common / "witful/sleeves"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


@contextmanager
def locked(repo: Path) -> Iterator[None]:
    """
    Serialize lifecycle operations locally; remote pushes provide the cross-machine boundary.

    Args:
        repo (Path): Existing repository or linked worktree.

    Yields:
        None: Exclusive ownership until the operation finishes or raises.
    """
    with (registry(repo) / "operation.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def save(repo: Path, sleeve: Sleeve) -> None:
    """
    Atomically persist a session receipt without publishing paths or source digests.

    Args:
        repo (Path): Checkout owning the common Git directory.
        sleeve (Sleeve): Validated lifecycle state.

    Returns:
        None: Receipt replaced under the caller's lifecycle lock.
    """
    path = registry(repo) / (sleeve.branch.rsplit("/", 1)[-1] + ".json")
    replace_file(path, (json.dumps(as_data(sleeve), indent=2) + "\n").encode(), expected=path.read_bytes() if path.exists() else None)


def sessions(repo: Path) -> tuple[Sleeve, ...]:
    """
    Read every local sleeve, including interrupted and completed sessions.

    Args:
        repo (Path): Existing repository or linked worktree.

    Returns:
        tuple[Sleeve, ...]: Receipts ordered by their opaque filenames.
    """
    return tuple(structure(json.loads(path.read_text()), Sleeve) for path in sorted(registry(repo).glob("*.json")))


def current(repo: Path) -> Sleeve:
    """
    Find the receipt for this exact worktree and verify branch ownership.

    Args:
        repo (Path): Sleeve worktree, not the shared parent checkout.

    Returns:
        Sleeve: Matching current session.

    Raises:
        SleeveError: No receipt matches or the checked-out branch changed.
    """
    root = git(repo, "rev-parse", "--show-toplevel").stdout.strip()
    sleeve = next((item for item in sessions(repo) if item.worktree == root), None)

    if sleeve is None:
        raise SleeveError("Run this command in the worktree returned by sleeve start.")
    if git(repo, "branch", "--show-current").stdout.strip() != sleeve.branch:
        raise SleeveError("Restore the sleeve's original branch before continuing.")

    return sleeve
