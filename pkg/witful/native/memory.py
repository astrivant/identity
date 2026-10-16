"""
Verify the explicitly selected macOS encrypted-swap development profile without extending it to other hosts.
"""

from __future__ import annotations

import platform
import re
import subprocess
from pathlib import Path

from witful.collection.protection import require_protected
from witful.exceptions import NativeError, StorageProtectionError


def require_macos_encrypted_swap(working_directory: str) -> None:
    """
    Require actual macOS encrypted swap and FileVault working storage for an explicit signed profile.

    Args:
        working_directory (str): Configured controller working directory on the admitted host.

    Returns:
        None: Host metadata verifies this narrower development acceptance rule.

    Raises:
        NativeError: Platform, storage or encrypted-swap evidence is missing or cannot be verified.
    """
    if platform.system() != "Darwin":
        raise NativeError("unsupported")
    try:
        require_protected(Path(working_directory))
        result = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "vm.swapusage"], check=False, capture_output=True, timeout=5, env={"LC_ALL": "C"}
        )
        metadata = result.stdout.decode("ascii").strip()
    except (OSError, ValueError, subprocess.TimeoutExpired, StorageProtectionError):
        raise NativeError("unavailable") from None
    amount = r"[0-9]+(?:\.[0-9]+)?[KMGT]"
    pattern = rf"total\s*=\s*{amount}\s+used\s*=\s*{amount}\s+free\s*=\s*{amount}\s+\(encrypted\)"
    if result.returncode or re.fullmatch(pattern, metadata) is None:
        raise NativeError("denied")
