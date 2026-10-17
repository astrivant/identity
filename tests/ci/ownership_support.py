"""
Share isolated Git fixture operations for ownership contract tests.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def git(root: Path, *args: str) -> str:
    """
    Run Git only within a synthetic repository without user hooks or signatures.

    Args:
        root (Path): Temporary test worktree.
        *args (str): Fixture commands.

    Returns:
        str: Captured Git output.
    """
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
