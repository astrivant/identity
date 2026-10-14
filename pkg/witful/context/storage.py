"""
Keep context receipts in private ignored storage and capture actual source/workspace bindings.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from witful.collection.protection import check_collection
from witful.completion.storage import git, identity, snapshots
from witful.context.core import digest
from witful.context.models import Observation

if TYPE_CHECKING:
    from pathlib import Path

    from witful.knowledge.models import Identity

MAX_INPUT_BYTES = 4 * 1024 * 1024


def read(path: Path) -> object:
    """
    Read a bounded JSON document for closed-contract validation at the caller.

    Args:
        path (Path): Explicit caller-selected local input.

    Returns:
        object: Parsed JSON, which the caller must validate against its closed schema.

    Raises:
        ValueError: The document exceeds the fixed adapter input ceiling.
    """
    with path.open("rb") as stream:
        content = stream.read(MAX_INPUT_BYTES + 1)
    if len(content) > MAX_INPUT_BYTES:
        raise ValueError("Context input exceeds adapter limit")
    value: object = json.loads(content)
    return value


def capture(root: Path, workspaces: tuple[Path, ...], observed_at: int, verified_at: int) -> tuple[Identity, Observation]:
    """
    Load only the selected collection after its managed-storage policy has passed.

    Args:
        root (Path): Explicit authorized collection root.
        workspaces (tuple[Path, ...]): Explicit task workspaces, never discovered from other identities.
        observed_at (int): Caller-supplied original snapshot observation time.
        verified_at (int): Current adapter verification time.

    Returns:
        tuple[Identity, Observation]: Validated tree and independently captured local bindings.

    Raises:
        ValueError: Source files escape the collection or exceed the adapter input ceiling.
        RuntimeError: Sources changed during capture.
    """
    check_collection(root)
    paths = (root / "lessons.jsonl", root / "knowledge/catalog.json")
    if any(path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size > MAX_INPUT_BYTES for path in paths):
        raise ValueError("Invalid context source boundary")
    revision = git(root, "rev-parse", "HEAD").decode().strip()
    before = tuple(path.read_bytes() for path in paths)
    tree = identity(root)
    current = snapshots((root, *workspaces))
    if tuple(path.read_bytes() for path in paths) != before:
        raise RuntimeError("Context sources changed during capture")
    if git(root, "rev-parse", "HEAD").decode().strip() != revision:
        raise RuntimeError("Collection revision changed during capture")
    state = digest({"workspaces": [{"path": item.path, "revision": item.revision, "digest": item.digest} for item in current]})
    return tree, Observation(revision, state, observed_at, verified_at, source_reads=6)


def destination(root: Path, output: Path) -> Path:
    """
    Restrict receipts to owner-controlled ignored runtime storage without following symlinks.

    Args:
        root (Path): Resolved collection root.
        output (Path): Requested receipt file.

    Returns:
        Path: Safe resolved JSON destination, with private parent permissions.

    Raises:
        ValueError: The destination escapes the receipt directory or follows a symlink.
    """
    directory = root / ".witful/context"
    output = output.absolute()
    if output.parent != directory or output.suffix != ".json":
        raise ValueError("Receipts belong directly under .witful/context")
    if any(path.is_symlink() for path in (directory.parent, directory, output)):
        raise ValueError("Receipt paths must not be symlinks")
    git(root, "check-ignore", "--quiet", str(output))
    check_collection(root)
    for path in (directory.parent, directory):
        path.mkdir(mode=0o700, exist_ok=True)
        path.chmod(0o700)
    if output.exists():
        output.chmod(0o600)
    return output
