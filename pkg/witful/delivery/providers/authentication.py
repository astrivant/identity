"""
Reuse platform token variables and existing host-specific CLI credential stores.
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Repository


def credential(repository: Repository) -> str:
    """
    Prefer platform token variables, then reuse an existing host-specific CLI login.

    Args:
        repository (Repository): Explicit selected host; Git credentials remain owned by Git.

    Returns:
        str: In-memory token, or empty for unauthenticated public reads.
    """
    if repository.provider == "github":
        variables = ("GH_TOKEN", "GITHUB_TOKEN") if repository.host == "github.com" else ("GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
        executable = "gh"
    else:
        variables, executable = ("GITLAB_TOKEN", "GLAB_TOKEN"), "glab"
    for variable in variables:
        if token := os.environ.get(variable):
            return token
    # CLI use is restricted to its credential store; every platform operation uses REST.
    try:
        result = subprocess.run(
            [executable, "auth", "token", "--hostname", repository.host], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""
