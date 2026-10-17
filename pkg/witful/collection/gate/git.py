"""
Read exact index blobs and committed history without checkout filters or replacement objects.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from attrs import frozen

from witful.exceptions import ArtifactGateError

if TYPE_CHECKING:
    from collections.abc import Sequence


@frozen
class Snapshot:
    """
    Bind publication policy and content to the same immutable Git object inventory.

    Attributes:
        root (Path): Existing Git checkout.
        entries (dict[str, tuple[str, str]]): Paths mapped to mode and blob identity.
    """

    root: Path
    entries: dict[str, tuple[str, str]]

    def read(self, name: str, limit: int) -> bytes:
        """
        Refuse unsupported modes and oversized blobs before loading their content.

        Args:
            name (str): Exact inventory path.
            limit (int): Maximum accepted blob bytes.

        Returns:
            bytes: Original blob, unaffected by unstaged changes or clean/smudge filters.
        """
        mode, oid = self.entries[name]
        if mode not in {"100644", "100755"}:
            raise ArtifactGateError("Publication artifacts must be regular files")
        size = int(git(self.root, "cat-file", "-s", oid))
        if size > limit:
            raise ArtifactGateError("Publication artifact exceeds its byte limit")
        data = git(self.root, "cat-file", "blob", oid)
        if len(data) != size:
            raise ArtifactGateError("Git blob size changed")
        return data


def git(root: Path, *arguments: str) -> bytes:
    """
    Run fixed local Git operations with bounded time and credential-safe failures.

    Args:
        root (Path): Existing checkout.
        *arguments (str): Separate literal Git arguments, never shell commands.

    Returns:
        bytes: Successful local Git output.
    """
    # A hook may inherit repository routing or tracing from its caller. Keep the
    # actual partial-commit index, but do not let other Git variables redirect reads.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    if arguments[:1] == ("ls-files",) and "GIT_INDEX_FILE" in os.environ:
        environment["GIT_INDEX_FILE"] = os.environ["GIT_INDEX_FILE"]
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", "-C", str(root), *arguments], capture_output=True, check=False, timeout=30, env=environment
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ArtifactGateError("Cannot inspect local Git publication objects") from None
    if result.returncode:
        raise ArtifactGateError("Cannot inspect local Git publication objects")
    return result.stdout


def commit(root: Path, reference: str) -> str:
    """
    Resolve an explicit ref or annotated tag to a full immutable commit identity.

    Args:
        root (Path): Existing checkout.
        reference (str): Literal caller-selected revision.

    Returns:
        str: Full commit object identity.
    """
    value = git(root, "rev-parse", "--verify", "--end-of-options", reference + "^{commit}").decode().strip()
    if not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", value):
        raise ArtifactGateError("Invalid commit identity")
    return value


def snapshot(root: Path, revision: str | None = None) -> Snapshot:
    """
    Capture the complete index or committed tree, rejecting unresolved index entries.

    Args:
        root (Path): Existing checkout.
        revision (str | None): Commit/ref to inspect; None selects the index.

    Returns:
        Snapshot: Complete path inventory with policy and content from one Git snapshot.
    """
    listing = (
        git(root, "ls-files", "--stage", "-z")
        if revision is None
        else git(root, "ls-tree", "-r", "-z", "--full-tree", commit(root, revision))
    )
    entries: dict[str, tuple[str, str]] = {}
    for row in listing.split(b"\0"):
        if not row:
            continue
        metadata, path = row.split(b"\t", 1)
        fields = metadata.decode("ascii").split()
        mode, oid = (fields[0], fields[1]) if revision is None else (fields[0], fields[2])
        name = path.decode("utf-8", errors="surrogateescape")
        if name in entries or (revision is None and fields[2] != "0"):
            raise ArtifactGateError("Resolve Git conflicts before checking publication")
        entries[name] = (mode, oid)
    return Snapshot(root, entries)


def history(root: Path, ranges: Sequence[tuple[str | None, str]], maximum: int) -> tuple[str, ...]:
    """
    Include every intermediate commit, not only the final tree or changed filenames.

    Args:
        root (Path): Existing complete Git checkout.
        ranges (Sequence[tuple[str | None, str]]): Exclusive old tip and inclusive new tip; None covers a new ref's full ancestry.
        maximum (int): Explicit review budget; exceeding it refuses the whole operation.

    Returns:
        tuple[str, ...]: Deduplicated immutable commits, including each new tip.
    """
    if maximum < 1 or git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise ArtifactGateError("History checks require a full clone and a positive commit budget")
    grafts = Path(git(root, "rev-parse", "--git-path", "info/grafts").decode().strip())
    if (root / grafts).exists():
        raise ArtifactGateError("Remove legacy Git grafts before checking publication history")
    selected: set[str] = set()
    for old, new in ranges:
        tip = commit(root, new)
        arguments = [tip] if old is None else [tip, "^" + commit(root, old)]
        values = git(root, "rev-list", f"--max-count={maximum + 1}", *arguments).decode().splitlines()
        selected.update((*values, tip))
        if len(selected) > maximum:
            raise ArtifactGateError("Publication history exceeds --max-commits; review and raise the explicit budget")
    return tuple(sorted(selected))
