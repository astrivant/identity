"""
Keep synthetic Git fixtures independent of the hook's owning worktree and index.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: MonkeyPatch) -> None:
    """
    Remove inherited Git routing and user configuration for each synthetic test.

    Args:
        monkeypatch (MonkeyPatch): Restore the invoking process environment after the test.

    Returns:
        None: Disposable fixtures cannot address the caller's Git directory or index.
    """
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
