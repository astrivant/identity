"""
Run bounded Git operations and verify private publication destinations.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

from witful.collection.process import private_repository
from witful.exceptions import SleeveError

if TYPE_CHECKING:
    from pathlib import Path


def git(root: Path, *arguments: str, allowed: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    """
    Capture Git diagnostics without exposing source contents or credentials.

    Args:
        root (Path): Existing checkout or worktree.
        *arguments (str): Literal Git arguments, never shell expressions.
        allowed (tuple[int, ...]): Expected exit statuses for predicates or merge conflicts.

    Returns:
        subprocess.CompletedProcess[str]: Captured result available to the caller.

    Raises:
        SleeveError: Git fails or exceeds the operation deadline.
    """
    try:
        result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise SleeveError("Git did not complete. Inspect the sleeve locally and retry; no closure was recorded.") from None

    if result.returncode not in allowed:
        raise SleeveError("Git failed. Inspect access, signing, hooks, or branch protection locally; private diagnostics withheld.")

    return result


def destination(root: Path, remote: str, expected: str | None = None) -> str:
    """
    Bind both fetch and push to the same private GitHub repository.

    Args:
        root (Path): Existing checkout.
        remote (str): Configured remote name.
        expected (str | None): Previously recorded repository identity.

    Returns:
        str: Verified GitHub owner/repository.

    Raises:
        SleeveError: Remote URLs differ, are unsupported, or changed since creation.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", remote):
        raise SleeveError("Select a configured remote name.")

    fetch = git(root, "remote", "get-url", "--all", remote).stdout.splitlines()
    push = git(root, "remote", "get-url", "--push", "--all", remote).stdout.splitlines()

    if len(fetch) != 1 or push != fetch:
        raise SleeveError("Multisleeving requires one identical fetch/push destination.")

    match = re.fullmatch(r"(?:git@github\.com:|https://github\.com/)([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)", fetch[0])

    if match is None:
        raise SleeveError("Multisleeving requires a private GitHub origin without embedded credentials.")

    repository = match[1].removesuffix(".git")

    if expected is not None and repository.lower() != expected.lower():
        raise SleeveError("The sleeve's publication destination changed; restore it before continuing.")

    private_repository(repository)
    return repository


def incoming(root: Path, remote: str, base: str, branch: str) -> str:
    """
    Fetch the integration head into a session-specific ref without relying on FETCH_HEAD.

    Args:
        root (Path): Existing checkout.
        remote (str): Validated remote name.
        base (str): Validated integration branch.
        branch (str): Unique sleeve branch.

    Returns:
        str: Fetched commit identifier.
    """
    ref = "refs/witful/" + branch + "/incoming"
    git(root, "fetch", "--no-tags", remote, f"refs/heads/{base}:{ref}")
    return git(root, "rev-parse", "--verify", ref + "^{commit}").stdout.strip()


def clean(root: Path) -> None:
    """
    Require a clean index and worktree while preserving ignored local runtime state.

    Args:
        root (Path): Sleeve checkout.

    Returns:
        None: No staged, unstaged, untracked, or unresolved changes remain.

    Raises:
        SleeveError: Work remains to checkpoint or reconcile.
    """
    if git(root, "status", "--porcelain", "--untracked-files=all").stdout:
        raise SleeveError("Checkpoint the sleeve's changes or resolve its merge first. The session remains open.")
