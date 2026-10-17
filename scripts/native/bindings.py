"""
Retain independent source bindings without a repository-wide mutable review stamp.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from attrs import frozen
from witful.knowledge.contracts import as_data, structure

if TYPE_CHECKING:
    from collections.abc import Mapping


@frozen
class Binding:
    """
    Bind one reviewed file to exact bytes and the source context of its last change.

    Attributes:
        path (str): Canonical repository-relative source or output path.
        sha256 (str): Digest of the reviewed bytes, including uncommitted edits.
        source_commit (str): HEAD at review, not a claim that the bytes were committed there.
        verification_date (str): Explicit review date retained until those bytes change.
    """

    path: str
    sha256: str
    source_commit: str
    verification_date: str


def location(path: str) -> Path:
    """
    Mirror a canonical source path beneath a caller-owned binding directory.

    Args:
        path (str): Repository-relative path to a reviewed file.

    Returns:
        Path: Relative JSON record path with the original filename preserved.

    Raises:
        ValueError: The path is empty, noncanonical or escapes the record directory.
    """
    candidate = PurePosixPath(path)
    if not path or candidate.is_absolute() or ".." in candidate.parts or str(candidate) != path or path == "." or "\\" in path:
        raise ValueError(f"Noncanonical binding path: {path}")
    return Path(path + ".json")


def read(directory: Path) -> dict[str, Binding]:
    """
    Read independent records and reject misplaced, malformed or ambiguous evidence.

    Args:
        directory (Path): Input or output record directory.

    Returns:
        dict[str, Binding]: Records indexed by their canonical source path.

    Raises:
        ValueError: A record has an invalid digest, location or duplicate path.
    """
    result: dict[str, Binding] = {}
    for file in sorted(directory.rglob("*.json")):
        item = structure(json.loads(file.read_text()), Binding)
        if file.relative_to(directory) != location(item.path) or item.path in result or not re.fullmatch(r"[a-f0-9]{64}", item.sha256):
            raise ValueError(f"Invalid diagram binding: {file}")
        result[item.path] = item
    return result


def reconcile(current: Mapping[str, str], retained: Mapping[str, Binding], revision: str, date: str) -> dict[str, Binding]:
    """
    Retain unchanged evidence and update only changed files in deterministic path order.

    Args:
        current (Mapping[str, str]): Complete current path-to-digest inventory.
        retained (Mapping[str, Binding]): Prior per-file review evidence.
        revision (str): Explicit source context for changed bytes.
        date (str): Explicit review date for changed bytes.

    Returns:
        dict[str, Binding]: Reconciled records without mutation of either input.
    """
    return {
        path: retained[path] if path in retained and retained[path].sha256 == digest else Binding(path, digest, revision, date)
        for path, digest in sorted(current.items())
    }


def write(directory: Path, records: Mapping[str, Binding]) -> None:
    """
    Write current records and remove only previously validated obsolete bindings.

    Args:
        directory (Path): Dedicated binding output directory.
        records (Mapping[str, Binding]): Complete reviewed inventory to retain.

    Returns:
        None: Current records are persisted; unchanged bytes are not rewritten.
    """
    previous = read(directory)
    for path, item in sorted(records.items()):
        file = directory / location(path)
        payload = json.dumps(as_data(item), indent=2) + "\n"
        if not file.exists() or file.read_text() != payload:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(payload)
    for path in previous.keys() - records.keys():
        (directory / location(path)).unlink()


def check(directory: Path, current: Mapping[str, str]) -> None:
    """
    Verify the complete merged inventory against actual source or output bytes.

    Args:
        directory (Path): Dedicated binding record directory.
        current (Mapping[str, str]): Complete actual inventory, discovered independently.

    Returns:
        None: Every current file is bound and no obsolete records remain.

    Raises:
        ValueError: Missing, changed or obsolete bindings require review and regeneration.
    """
    retained = {path: item.sha256 for path, item in read(directory).items()}
    changed = sorted(path for path in retained.keys() | current.keys() if retained.get(path) != current.get(path))
    if changed:
        raise ValueError("Review and regenerate native diagram bindings: " + ", ".join(changed))
