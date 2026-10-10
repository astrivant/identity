"""
Validate publication destinations, review gates, and actionable privacy-safe CLI errors.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from witful.sleeves import operations, state
from witful.sleeves.cli import main
from witful.sleeves.git import destination
from witful.sleeves.models import SleeveError

if TYPE_CHECKING:
    from pytest import CaptureFixture, MonkeyPatch


@pytest.mark.parametrize(
    "url", ["https://example.invalid/a/b", "https://" + "secret@" + "github.com/example/identity", "https://github.com/example/identity"]
)
def test_destination_rejects_redirects_and_changed_identity(tmp_path: Path, url: str) -> None:
    """
    Reject unsupported or changed repositories before attempting a GitHub access check.

    Args:
        tmp_path (Path): Empty local Git repository.
        url (str): Unsafe or unexpected remote destination.

    Returns:
        None: No credentialed network operation occurs.
    """
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", url], check=True)
    with pytest.raises(SleeveError):
        destination(tmp_path, "origin", "example/other")


def test_review_path_stays_open_until_real_merge(repository: Path, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Back up a reviewed sleeve but never treat PR creation as completed integration.

    Args:
        repository (Path): Synthetic checkout.
        tmp_path (Path): Sleeve directory.
        monkeypatch (MonkeyPatch): Replace only GitHub PR operations.

    Returns:
        None: A proposed merge does not pass the closure guard.
    """
    sleeve = operations.start(repository, tmp_path / "sleeve", name="review")
    root = Path(sleeve.worktree)
    (root / "review.md").write_text("Needs review.\n")
    operations.checkpoint(root, ("review.md",), "Reviewable change")
    calls: list[list[str]] = []

    def github(arguments: list[str]) -> bytes:
        """
        Record proposal operations without contacting GitHub.

        Args:
            arguments (list[str]): GitHub CLI operation.

        Returns:
            bytes: No existing PR is present in this fixture.
        """
        calls.append(arguments)
        return b""

    monkeypatch.setattr(operations, "run", github)
    with pytest.raises(SleeveError, match="awaits merge"):
        operations.finish(root, pull_request=True)
    assert [call[2] for call in calls] == ["list", "create"]
    assert state.current(root).closed_commit is None
    with pytest.raises(SleeveError):
        operations.guard(root)


def test_cli_redacts_source_validation_failure(monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    """
    Keep private validation payloads out of CLI diagnostics.

    Args:
        monkeypatch (MonkeyPatch): Inject a source failure containing a synthetic sentinel.
        capsys (CaptureFixture[str]): Captured terminal output.

    Returns:
        None: The failure is nonzero and its private source value is absent.
    """

    def fail(repo: Path) -> None:
        """
        Raise a synthetic private source error.

        Args:
            repo (Path): Unused test repository.

        Returns:
            None: This fixture always raises.
        """
        raise ValueError("SYNTHETIC_PRIVATE_SENTINEL")

    monkeypatch.setattr(operations, "guard", fail)
    with pytest.raises(SystemExit) as error:
        main(["guard"])
    assert error.value.code == 2
    assert "SYNTHETIC_PRIVATE_SENTINEL" not in capsys.readouterr().err
