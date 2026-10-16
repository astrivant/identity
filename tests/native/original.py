"""
Build exact synthetic original Git objects for independent archival and recipient recovery contracts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from witful.native.git import git
from witful.native.original_git import plumbing

if TYPE_CHECKING:
    from pathlib import Path


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
