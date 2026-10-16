"""
Verify explicit macOS encrypted-swap acceptance without silently relaxing signed native protection controls.
"""

from __future__ import annotations

import platform
import subprocess
from typing import TYPE_CHECKING

import pytest
from witful.exceptions import NativeError, StorageProtectionError
from witful.native import memory

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("host", "output", "returncode", "accepted"),
    (
        ("Darwin", b"total = 14336.00M  used = 13227.44M  free = 1108.56M  (encrypted)\n", 0, True),
        ("Linux", b"total = 10.00M used = 1.00M free = 9.00M (encrypted)", 0, False),
        ("Darwin", b"total = 10.00M used = 1.00M free = 9.00M (unencrypted)", 0, False),
        ("Darwin", b"total = 10.00M used = 1.00M free = 9.00M (encrypted)", 1, False),
        ("Darwin", b"unknown encrypted status", 0, False),
    ),
)
def test_mac_profile_checks_actual_host_metadata(
    monkeypatch: pytest.MonkeyPatch, host: str, output: bytes, returncode: int, accepted: bool
) -> None:
    """
    Reject other platforms, failed commands and ambiguous encryption metadata.

    Args:
        monkeypatch (pytest.MonkeyPatch): Scoped synthetic host observation.
        host (str): Reported operating system.
        output (bytes): Synthetic sysctl response.
        returncode (int): Host command status.
        accepted (bool): Expected verified encrypted-swap result.

    Returns:
        None: Only the explicit successful macOS observation is accepted.
    """
    monkeypatch.setattr(platform, "system", lambda: host)
    monkeypatch.setattr(memory, "require_protected", lambda path: None)

    def run(
        arguments: list[str], *, check: bool, capture_output: bool, timeout: int, env: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        """
        Observe the fixed bounded system command without accessing the actual host.

        Args:
            arguments (list[str]): Fixed sysctl invocation.
            check (bool): Whether raw-output exceptions are enabled.
            capture_output (bool): Captured metadata flag.
            timeout (int): Verification deadline.
            env (dict[str, str]): Deterministic locale without inherited credentials.

        Returns:
            subprocess.CompletedProcess[bytes]: Supplied host evidence.
        """
        assert arguments == ["/usr/sbin/sysctl", "-n", "vm.swapusage"]
        assert not check and capture_output and timeout == 5 and env == {"LC_ALL": "C"}
        return subprocess.CompletedProcess(arguments, returncode, output, b"")

    monkeypatch.setattr(subprocess, "run", run)
    if accepted:
        memory.require_macos_encrypted_swap("/protected/runtime")
    else:
        with pytest.raises(NativeError):
            memory.require_macos_encrypted_swap("/protected/runtime")


def test_mac_profile_still_requires_protected_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep encrypted working storage mandatory even when encrypted swap is explicitly accepted.

    Args:
        monkeypatch (pytest.MonkeyPatch): Synthetic failing storage verifier.

    Returns:
        None: The profile fails before any key access on an unprotected volume.
    """
    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    def denied(path: Path) -> None:
        """
        Supply a negative protected-storage observation.

        Args:
            path (Path): Requested working storage.

        Returns:
            None: Never returns normally.

        Raises:
            StorageProtectionError: Storage is not verified.
        """
        raise StorageProtectionError("Synthetic negative result")

    monkeypatch.setattr(memory, "require_protected", denied)
    with pytest.raises(NativeError, match="unavailable"):
        memory.require_macos_encrypted_swap("/unprotected/runtime")
