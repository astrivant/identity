"""
Retain review cadence across real Git merges without accepting unrelated history.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

import pytest
from witful.reflection.planning import _cadence

if TYPE_CHECKING:
    from pathlib import Path


def git(root: Path, *arguments: str) -> str:
    """
    Operate only on a synthetic local repository with no user hooks or signing keys.

    Args:
        root (Path): Test-owned checkout.
        *arguments (str): Literal Git arguments.

    Returns:
        str: Captured metadata or empty command output.
    """
    return subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.org",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            *arguments,
        ],
        env={
            **{key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
        text=True,
        stderr=subprocess.PIPE,
        timeout=10,
    ).strip()


def test_merged_review_anchor_keeps_original_and_effective_boundaries(tmp_path: Path) -> None:
    """
    Count from first integration of a reviewed side branch, preserving failures for unmerged anchors.

    Args:
        tmp_path (Path): Empty test-owned directory.

    Returns:
        None: Merge, later commits, ordinary anchors and divergent history have distinct results.
    """
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "commit", "-qm", "Baseline", "--allow-empty")
    initial = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "checkout", "-qb", "review")
    git(tmp_path, "commit", "-qm", "Reviewed boundary", "--allow-empty")
    anchor = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "checkout", "main")
    git(tmp_path, "commit", "-qm", "Concurrent work", "--allow-empty")
    current = git(tmp_path, "rev-parse", "HEAD")
    commits = git(tmp_path, "rev-list", "--first-parent", current).splitlines()
    with pytest.raises(ValueError, match="not reachable"):
        _cadence(tmp_path, current, anchor, commits)
    git(tmp_path, "merge", "--no-ff", "review", "-m", "Integrate review")
    merged = git(tmp_path, "rev-parse", "HEAD")
    commits = git(tmp_path, "rev-list", "--first-parent", merged).splitlines()
    assert anchor not in commits
    assert _cadence(tmp_path, merged, anchor, commits) == (0, merged)
    git(tmp_path, "commit", "-qm", "After integration", "--allow-empty")
    current = git(tmp_path, "rev-parse", "HEAD")
    commits = git(tmp_path, "rev-list", "--first-parent", current).splitlines()
    assert _cadence(tmp_path, current, anchor, commits) == (1, merged)
    assert _cadence(tmp_path, current, initial, commits) == (3, initial)
    assert _cadence(tmp_path, current, None, commits) == (4, None)
    with pytest.raises(ValueError, match="missing or divergent"):
        _cadence(tmp_path, current, "f" * 40, commits)
