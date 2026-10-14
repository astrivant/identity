"""
Check installer ownership, idempotence, and source boundaries without making GitHub changes.
"""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

import pytest
from witful.collection import install
from witful.collection.models import Config

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.mark.parametrize("repository", ["astrivant/identity", "owner/repo/extra", "--help", ""])
def test_setup_rejects_wrong_destinations_before_tools(tmp_path: Path, repository: str, monkeypatch: MonkeyPatch) -> None:
    """
    Refuse upstream or malformed targets before invoking GitHub or generating keys.

    Args:
        tmp_path (Path): Isolated paths.
        repository (str): Invalid private destination.
        monkeypatch (MonkeyPatch): Tool boundary that must never execute.

    Returns:
        None: No local or remote state is created.
    """

    def forbidden(arguments: list[str], **kwargs: object) -> bytes:
        """
        Fail if a tool is invoked before destination validation.

        Args:
            arguments (list[str]): Unexpected tool invocation.
            **kwargs (object): Unexpected keyword arguments.

        Returns:
            bytes: No successful result is possible.
        """
        raise AssertionError("A tool ran before destination validation")

    monkeypatch.setattr(install, "run", forbidden)

    with pytest.raises(ValueError):
        install.setup(repository, tmp_path / "checkout", tmp_path / "home", tmp_path / "keys")

    assert list(tmp_path.iterdir()) == []


def test_setup_preserves_home_and_reuses_configuration(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Exercise private installation and retry with all GitHub and key operations isolated.

    Args:
        tmp_path (Path): Synthetic private checkout, home, and backup directories.
        monkeypatch (MonkeyPatch): External side-effect boundaries.

    Returns:
        None: Preferences and readable-figure choices survive setup, and enablement follows secret projection.
    """
    checkout, home, keys = tmp_path / "checkout", tmp_path / "home", tmp_path / "keys"
    checkout.mkdir()
    home.mkdir()
    keys.mkdir()
    (home / "config.toml").write_text('model = "existing"\n')
    (home / "auth.json").write_text("credential fixture")
    (checkout / ".github").mkdir()
    (checkout / ".github/settings.yml").write_text("repository:\n  name: identity\n  private: false\n")
    (keys / "cosign.pub").write_text("synthetic public key")
    calls: list[str] = []

    def tool(arguments: list[str], **kwargs: object) -> bytes:
        """
        Return owned repository metadata and record only nonsecret tool names.

        Args:
            arguments (list[str]): Literal command arguments.
            **kwargs (object): Working directory or stdin context.

        Returns:
            bytes: Synthetic origin URL or empty success.
        """
        if arguments[:4] == ["git", "remote", "get-url", "origin"]:
            return b"git@github.com:example/private.git\n"
        calls.append(" ".join(arguments[:3]))
        return b""

    monkeypatch.setattr(install, "require_protected", lambda path: None)
    config = Config("example/private", "a" * 64, "b" * 64)
    monkeypatch.setattr(shutil, "which", lambda tool: tool)
    monkeypatch.setattr(install, "run", tool)
    monkeypatch.setattr(install, "private_repository", lambda repository: None)
    monkeypatch.setattr(install, "prepare", lambda directory, repository: config)
    monkeypatch.setattr(install, "fingerprint", lambda public: "b" * 64)
    monkeypatch.setattr(install, "seal", lambda *args: None)
    monkeypatch.setattr(install, "project", lambda *args: calls.append("secrets"))
    install.setup("example/private", checkout, home, keys)
    assert calls == ["secrets", "gh variable set"]
    assert (home / "config.toml").read_text() == 'model = "existing"\n'
    assert (home / "auth.json").read_text() == "credential fixture"
    assert (home / "collection/.gitignore").read_text() == "*\n"
    assert (home / "skills/witful-collection/SKILL.md").is_file()
    assert "private: true" in (checkout / ".github/settings.yml").read_text()
    path = checkout / ".config/collection.json"
    current = json.loads(path.read_text())
    current["publish_figures"] = True
    path.write_text(json.dumps(current))
    install.setup("example/private", checkout, home, keys)
    assert json.loads(path.read_text())["publish_figures"] is True
    assert calls == ["secrets", "gh variable set", "secrets", "gh variable set"]
