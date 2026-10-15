"""
Restore exact original Git object identities, signed-header bytes and available repository metadata from encrypted native archives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from attrs import evolve
from witful.exceptions import NativeError
from witful.native import original_git
from witful.native.backup import Archive, archive, verify
from witful.native.git import git
from witful.native.original_git import GIT_ARCHIVE, capture, observe, plumbing, restore

if TYPE_CHECKING:
    from pathlib import Path

    from tests.native.runtime import Runtime


def source_repository(directory: Path) -> tuple[str, str]:
    """
    Construct original canonical Git objects containing synthetic signature bytes and an available unreachable blob.

    Args:
        directory (Path): Empty disposable Git directory.

    Returns:
        tuple[str, str]: Original commit and annotated-tag OIDs; signature bytes are retention fixtures, not cryptographic trust evidence.
    """
    directory.mkdir()
    git(directory, ("init", "--bare", "--template=", "."))
    blob = plumbing(directory, ("hash-object", "-w", "--stdin"), 4096, b"private-original-git-canary\n").strip()
    tree = plumbing(directory, ("mktree",), 4096, b"100644 blob " + blob + b"\tlesson.txt\n").strip()
    signature = b"-----BEGIN PGP SIGNATURE-----\n synthetic archival bytes only\n -----END PGP SIGNATURE-----"
    commit_bytes = (
        b"tree "
        + tree
        + b"\nauthor Synthetic <fixture@example.invalid> 0 +0000\ncommitter Synthetic <fixture@example.invalid> 0 +0000\ngpgsig "
        + signature
        + b"\n\nOriginal commit\n"
    )
    commit = plumbing(directory, ("hash-object", "-w", "-t", "commit", "--stdin"), 4096, commit_bytes).strip()
    tag_bytes = (
        b"object "
        + commit
        + b"\ntype commit\ntag archived\ntagger Synthetic <fixture@example.invalid> 0 +0000\n\nOriginal annotated tag\n"
        + signature
    )
    tag = plumbing(directory, ("hash-object", "-w", "-t", "tag", "--stdin"), 4096, tag_bytes).strip()
    plumbing(directory, ("update-ref", "refs/heads/main", commit.decode()), 4096)
    plumbing(directory, ("symbolic-ref", "HEAD", "refs/heads/main"), 4096)
    plumbing(directory, ("update-ref", "refs/tags/archived", tag.decode()), 4096)
    plumbing(directory, ("hash-object", "-w", "--stdin"), 4096, b"explicitly retained unreachable bytes")
    hooks = directory / "hooks"
    hooks.mkdir()
    (hooks / "pre-receive").write_bytes(b"#!/bin/sh\nexit 98\n")
    (hooks / "pre-receive").chmod(0o700)
    (directory / "custom-recovery-receipt").write_bytes(b"synthetic ancillary receipt")
    return commit.decode(), tag.decode()


def test_exact_original_git_round_trip(runtime: Runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Preserve original commits, tags, unreachable content and ancillary bytes without publishing plaintext or running original hooks.

    Args:
        runtime (Runtime): Real native persistence backend and independent synthetic custody.
        tmp_path (Path): Disposable synthetic repository workspace.
        monkeypatch (pytest.MonkeyPatch): Explicit synthetic-only protected-storage stand-in.

    Returns:
        None: Restored original object IDs and source metadata match, while the native database or local Git contains ciphertext.
    """
    monkeypatch.setattr(original_git, "require_protected", lambda _: None)
    directory = tmp_path / "original.git"
    commit, tag = source_repository(directory)
    original = observe(directory, True, True, runtime.service.budget.bytes, 4096)
    operation = str(uuid4())
    receipt = capture(runtime.service, runtime.access, operation, directory, True, True)
    assert capture(runtime.service, runtime.access, operation, directory, True, True) == receipt
    _, frontier = runtime.service.snapshot(runtime.access, "export", "*")
    archived = next(pointer for pointer in frontier.archives if pointer.kind == GIT_ARCHIVE)
    restored = tmp_path / "restored.git"
    inventory = restore(runtime.service, runtime.access, archived.record, restored)
    assert inventory.unreachable and inventory.reflogs
    assert archive(runtime.service, runtime.access)[1]
    retained = runtime.service.store.history(runtime.access.scope)
    damaged = evolve(retained[0], objects=retained[0].objects[1:])
    with pytest.raises(NativeError):
        verify(runtime.service, runtime.access, Archive(runtime.access.scope, (damaged, *retained[1:])))
    assert observe(restored, True, True, runtime.service.budget.bytes, 4096).objects == original.objects
    assert plumbing(restored, ("rev-parse", "HEAD"), 4096).strip().decode() == commit
    assert plumbing(restored, ("rev-parse", "refs/tags/archived"), 4096).strip().decode() == tag
    for name, _, data in original.files:
        assert (restored / name).read_bytes() == data
    for batch in runtime.service.store.history(runtime.access.scope):
        assert b"private-original-git-canary" not in b"".join(item.payload for item in batch.objects)
    with pytest.raises(NativeError):
        restore(runtime.service, runtime.access, archived.record, restored)
    assert (restored / "HEAD").exists()


def test_original_inventory_rejects_external_symlinks(tmp_path: Path) -> None:
    """
    Refuse a local Git metadata symlink instead of copying a file outside the reviewed repository inventory.

    Args:
        tmp_path (Path): Disposable synthetic source and excluded file.

    Returns:
        None: No external data becomes an implicitly included archival record.
    """
    directory = tmp_path / "source.git"
    source_repository(directory)
    outside = tmp_path / "outside"
    outside.write_bytes(b"not-in-reviewed-source")
    (directory / "external").symlink_to(outside)
    with pytest.raises(NativeError, match="unsupported"):
        observe(directory, True, True, 1024 * 1024, 4096)


def test_original_inventory_rejects_root_symlink(tmp_path: Path) -> None:
    """
    Reject a symlink selected as the source root before any Git process can follow it.

    Args:
        tmp_path (Path): Disposable original repository and alias.

    Returns:
        None: The explicit inventory boundary includes its root.
    """
    directory = tmp_path / "source.git"
    source_repository(directory)
    alias = tmp_path / "alias.git"
    alias.symlink_to(directory, target_is_directory=True)
    with pytest.raises(NativeError, match="unsupported"):
        observe(alias, True, True, 1024 * 1024, 4096)


def test_git_plumbing_ignores_ambient_routing_and_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Prevent caller environment from rerouting objects or spilling Git diagnostics outside the admitted workspace.

    Args:
        tmp_path (Path): Disposable isolated repositories and excluded trace destination.
        monkeypatch (pytest.MonkeyPatch): Ambient environment contamination.

    Returns:
        None: The selected repository is read and no trace file is written.
    """
    selected, other = tmp_path / "selected.git", tmp_path / "other.git"
    expected, _ = source_repository(selected)
    other.mkdir()
    git(other, ("init", "--bare", "--template=", "."))
    trace = tmp_path / "excluded-trace"
    monkeypatch.setenv("GIT_DIR", str(other))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(other / "objects"))
    monkeypatch.setenv("GIT_TRACE", str(trace))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    assert git(selected, ("rev-parse", "HEAD")).strip().decode() == expected
    assert not trace.exists()
