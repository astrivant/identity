"""
Reject stale, dirty, excluded and escaping source inputs before invoking the SDK.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from witful.codegraph.snapshot import capture
from witful.exceptions import NativeError

from tests.codegraph.support import command, repository

if TYPE_CHECKING:
    from pathlib import Path


def test_capture_coverage_and_untrusted_text(tmp_path: Path) -> None:
    """
    Preserve source as data, expose unsupported/untracked coverage and apply exclusions first.

    Args:
        tmp_path (Path): Disposable fixture root.

    Returns:
        None: Only explicitly selected Python bytes reach the worker input.
    """
    enrollment, revision = repository(tmp_path / "source")
    (tmp_path / "source/untracked.py").write_text("sensitive = True")
    snapshot = capture(enrollment, revision)
    assert snapshot.untracked
    assert len(snapshot.sources) == 1
    assert "untrusted fixture" in snapshot.sources[0].text
    assert snapshot.files[0].coverage == "unsupported"
    assert capture(evolve(enrollment, excluded=("*.py",)), revision).sources == ()


@pytest.mark.parametrize("change", ["dirty", "staged", "symlink", "nested", "wrong-revision", "budget"])
def test_rejected_source_boundaries(tmp_path: Path, change: str) -> None:
    """
    Fail closed on incomplete or unauthorized source states.

    Args:
        tmp_path (Path): Disposable fixture root.
        change (str): Seeded source boundary violation.

    Returns:
        None: Invalid source states never become graph input.
    """
    root = tmp_path / "source"
    enrollment, revision = repository(root)
    if change in {"dirty", "staged"}:
        (root / "sample.py").write_text("changed = True")
        if change == "staged":
            command(root, "add", "sample.py")
    elif change == "symlink":
        (root / "sample.py").unlink()
        (root / "sample.py").symlink_to(root / "README.md")
    elif change == "nested":
        (root / "nested").mkdir()
        (root / "nested/child.py").write_text("value = 1")
        command(root, "add", "nested/child.py")
        command(root, "commit", "-m", "Add nested source")
        revision = command(root, "rev-parse", "HEAD")
        (root / "nested/.git").mkdir()
    elif change == "wrong-revision":
        revision = "0" * 40
    else:
        enrollment = evolve(enrollment, source_bytes=1)
    with pytest.raises(NativeError):
        capture(enrollment, revision)


def test_repository_fsmonitor_never_executes(tmp_path: Path) -> None:
    """
    Treat Git configuration hooks as executable untrusted repository input.

    Args:
        tmp_path (Path): Disposable fixture root.

    Returns:
        None: Metadata inspection never invokes the configured command.
    """
    root = tmp_path / "source"
    enrollment, revision = repository(root)
    command(root, "config", "core.fsmonitor", "echo unsafe > executed-marker")
    capture(enrollment, revision)
    assert not (root / "executed-marker").exists()


def test_sdk_capture_defers_language_detection(tmp_path: Path) -> None:
    """
    Preserve detector inputs without imposing a parallel extension or language registry.

    Args:
        tmp_path (Path): Disposable tracked fixture.

    Returns:
        None: All selected text reaches upstream detection; binary and excluded inputs remain visible.
    """
    root = tmp_path / "source"
    enrollment, _ = repository(root)
    (root / "custom.future").write_text("a future parser may recognize this\n")
    (root / "binary.dat").write_bytes(b"\x00\xff")
    command(root, "add", ".")
    command(root, "commit", "-m", "Add unknown extension and binary fixture")
    revision = command(root, "rev-parse", "HEAD")
    snapshot = capture(evolve(enrollment, profile="sdk", excluded=("sample.py",)), revision)
    assert {source.path for source in snapshot.sources} == {"README.md", "custom.future"}
    statuses = {file.path: file.coverage for file in snapshot.files}
    assert statuses == {"README.md": "pending", "binary.dat": "non-text", "custom.future": "pending", "sample.py": "excluded"}
