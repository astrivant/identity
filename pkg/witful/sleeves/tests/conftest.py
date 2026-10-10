"""
Exercise independent sleeves against real local Git remotes without GitHub or provider calls.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from witful.sleeves import operations
from witful.sleeves.git import git

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """
    Create a synthetic private-repository boundary with real SSH-signed Git commits.

    Args:
        tmp_path (Path): Isolated test directory.
        monkeypatch (MonkeyPatch): Replace only GitHub visibility checks.

    Returns:
        Path: Source checkout whose origin is a local bare repository.
    """
    remote, root, key = tmp_path / "remote.git", tmp_path / "identity", tmp_path / "signing"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True, capture_output=True)
    for name, value in {
        "user.name": "Example",
        "user.email": "example@example.com",
        "gpg.format": "ssh",
        "user.signingkey": str(key),
        "core.hooksPath": str(tmp_path / "empty-hooks"),
    }.items():
        git(root, "config", name, value)
    (root / "instructions.md").write_text("Base policy.\n")
    git(root, "add", "instructions.md")
    git(root, "-c", "commit.gpgsign=true", "commit", "-m", "Synthetic baseline")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "-u", "origin", "main")
    monkeypatch.setattr(operations, "destination", lambda *args: "example/identity")
    return root
