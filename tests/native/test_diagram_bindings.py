"""
Exercise independent diagram evidence changes through real Git merges and integrity checks.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from typing import TYPE_CHECKING

import pytest
from native.bindings import Binding, check, location, read, reconcile, write

from tests.ci.ownership_support import git

if TYPE_CHECKING:
    from pathlib import Path


def hashes(first: str = "initial", second: str = "initial") -> dict[str, str]:
    """
    Produce two independent synthetic source bindings.

    Args:
        first (str): First file contents.
        second (str): Second file contents.

    Returns:
        dict[str, str]: Exact synthetic file digests.
    """
    return {name: hashlib.sha256(value.encode()).hexdigest() for name, value in (("pkg/a.py", first), ("pkg/b.py", second))}


@pytest.mark.parametrize("same_file", [False, True])
def test_concurrent_branches_merge_only_independent_records(tmp_path: Path, same_file: bool) -> None:
    """
    Let Git combine distinct bindings while retaining conflicts for competing evidence.

    Args:
        tmp_path (Path): Isolated synthetic repository.
        same_file (bool): Whether both branches revise the same binding.

    Returns:
        None: Independent changes merge and validate; competing changes still conflict.
    """
    git(tmp_path, "init", "--initial-branch=main")
    git(tmp_path, "config", "user.name", "Fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    directory = tmp_path / "bindings"
    write(directory, reconcile(hashes(), {}, "a" * 40, "2026-10-15"))
    git(tmp_path, "add", "bindings")
    git(tmp_path, "commit", "-m", "Baseline")
    git(tmp_path, "checkout", "-b", "first")
    write(directory, reconcile(hashes(first="first"), read(directory), "b" * 40, "2026-10-16"))
    git(tmp_path, "add", "bindings")
    git(tmp_path, "commit", "-m", "First independent change")
    git(tmp_path, "checkout", "-b", "second", "main")
    changes = hashes(first="second") if same_file else hashes(second="second")
    write(directory, reconcile(changes, read(directory), "c" * 40, "2026-10-17"))
    git(tmp_path, "add", "bindings")
    git(tmp_path, "commit", "-m", "Second independent change")
    if same_file:
        with pytest.raises(subprocess.CalledProcessError):
            git(tmp_path, "merge", "first", "--no-edit")
        assert "UU bindings/pkg/a.py.json" in git(tmp_path, "status", "--short")
    else:
        git(tmp_path, "merge", "first", "--no-edit")
        check(directory, hashes(first="first", second="second"))
        assert read(directory)["pkg/a.py"].source_commit == "b" * 40
        assert read(directory)["pkg/b.py"].source_commit == "c" * 40


def test_repeat_review_preserves_unchanged_bytes_and_history(tmp_path: Path) -> None:
    """
    Keep commit/date churn out of unchanged evidence, including reordered inventories.

    Args:
        tmp_path (Path): Isolated binding directory.

    Returns:
        None: Reconciliation is deterministic and leaves caller inputs and unchanged files intact.
    """
    current = hashes()
    retained = reconcile(current, {}, "a" * 40, "2026-10-15")
    before = dict(retained)
    write(tmp_path, retained)
    files = {file: (file.read_bytes(), file.stat().st_mtime_ns) for file in tmp_path.rglob("*.json")}
    result = reconcile(dict(reversed(list(current.items()))), retained, "b" * 40, "2026-10-17")
    write(tmp_path, result)
    assert result == retained == before
    assert list(result) == sorted(result)
    assert current == hashes()
    assert {file: (file.read_bytes(), file.stat().st_mtime_ns) for file in files} == files


@pytest.mark.parametrize("change", ["modified", "missing", "removed", "extra", "digest", "path"])
def test_integrity_and_complete_membership_remain_required(tmp_path: Path, change: str) -> None:
    """
    Reject source, membership and evidence tampering after recombination.

    Args:
        tmp_path (Path): Isolated record directory.
        change (str): Independent mismatch to inject.

    Returns:
        None: The normal check refuses each stale or malformed inventory.
    """
    current = hashes()
    write(tmp_path, reconcile(current, {}, "a" * 40, "2026-10-15"))
    file = tmp_path / location("pkg/a.py")
    if change == "modified":
        current = hashes(first="changed")
    elif change == "missing":
        file.unlink()
    elif change == "removed":
        current.pop("pkg/a.py")
    elif change == "extra":
        current["pkg/new.py"] = "a" * 64
    else:
        record = json.loads(file.read_text())
        record["sha256" if change == "digest" else "path"] = "invalid"
        file.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        check(tmp_path, current)


def test_removal_prunes_only_known_obsolete_records(tmp_path: Path) -> None:
    """
    Remove bindings for deleted sources without touching neighboring maintained files.

    Args:
        tmp_path (Path): Isolated binding directory.

    Returns:
        None: A deleted source has no stale record and unrelated data stays unchanged.
    """
    current = hashes()
    write(tmp_path, reconcile(current, {}, "a" * 40, "2026-10-15"))
    unrelated = tmp_path / "README.md"
    unrelated.write_text("Retain this note.\n")
    current.pop("pkg/a.py")
    write(tmp_path, reconcile(current, read(tmp_path), "b" * 40, "2026-10-17"))
    check(tmp_path, current)
    assert not (tmp_path / location("pkg/a.py")).exists()
    assert unrelated.read_text() == "Retain this note.\n"


@pytest.mark.parametrize("path", ["", ".", "/absolute", "../escape", "pkg/../escape", "pkg//file", "pkg\\file"])
def test_record_paths_cannot_escape_or_alias(path: str) -> None:
    """
    Require one canonical record name per source path.

    Args:
        path (str): Unsupported path spelling.

    Returns:
        None: Invalid paths fail before any record is written.
    """
    with pytest.raises(ValueError):
        location(path)


def test_existing_review_migrates_without_invented_provenance(tmp_path: Path) -> None:
    """
    Preserve an old aggregate record's review fields when splitting its existing facts.

    Args:
        tmp_path (Path): Isolated binding directory.

    Returns:
        None: Serialization retains the original review, even at a newer source HEAD.
    """
    prior = {path: Binding(path, digest, "a" * 40, "2026-10-15") for path, digest in hashes().items()}
    write(tmp_path, reconcile(hashes(), prior, "b" * 40, "2026-10-17"))
    assert read(tmp_path) == prior
