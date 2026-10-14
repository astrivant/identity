"""
Validate host-encryption evidence without changing the test machine or accepting unknown storage.
"""

from __future__ import annotations

import json
import platform
import plistlib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from witful.collection import protection
from witful.collection.protection import check_collection, require_protected
from witful.exceptions import StorageProtectionError

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.mark.parametrize("enabled", [True, False, "true", None])
def test_filevault_requires_boolean_evidence(tmp_path: Path, monkeypatch: MonkeyPatch, enabled: bool | str | None) -> None:
    """
    Accept only explicit FileVault evidence and never create the requested target.

    Args:
        tmp_path (Path): Existing ancestor of a future private destination.
        monkeypatch (MonkeyPatch): Synthetic platform and disk metadata.
        enabled (bool | str | None): Reported encryption field.

    Returns:
        None: Unknown, false, and malformed metadata fail closed.
    """
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    payload = plistlib.dumps({} if enabled is None else {"FileVault": enabled})
    monkeypatch.setattr(
        protection,
        "_read",
        lambda arguments: (
            b"Filesystem 512-blocks Used Available Capacity Mounted on\n/dev/disk1s1 100 50 50 50% /private\n"
            if arguments[0] == "/bin/df"
            else payload
        ),
    )
    destination = tmp_path / "not-created/private"

    if enabled is True:
        require_protected(destination)
    else:
        with pytest.raises(StorageProtectionError):
            require_protected(destination)

    assert not destination.exists()


@pytest.mark.parametrize("protected", [True, False])
def test_linux_requires_encryption_on_every_backing_route(tmp_path: Path, monkeypatch: MonkeyPatch, protected: bool) -> None:
    """
    Reject mixed encrypted and unencrypted ancestry rather than accepting any crypt node.

    Args:
        tmp_path (Path): Synthetic mount path.
        monkeypatch (MonkeyPatch): Bounded system-command responses.
        protected (bool): Whether every storage branch passes an encryption mapping.

    Returns:
        None: LVM over encrypted devices passes; an uncovered backing branch fails.
    """
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    def metadata(arguments: list[str]) -> bytes:
        """
        Return minimal findmnt or inverse-lsblk output.

        Args:
            arguments (list[str]): Fixed metadata utility command.

        Returns:
            bytes: Encoded synthetic host metadata.
        """
        if arguments[0] == "findmnt":
            return json.dumps({"filesystems": [{"fstype": "ext4", "source": "/dev/mapper/private"}]}).encode()
        children = [{"type": "crypt"}, {"type": "crypt" if protected else "disk"}]
        return json.dumps({"blockdevices": [{"type": "lvm", "children": children}]}).encode()

    monkeypatch.setattr(protection, "_read", metadata)

    if protected:
        require_protected(tmp_path)
    else:
        with pytest.raises(StorageProtectionError):
            require_protected(tmp_path)


@pytest.mark.parametrize("swap", [False, True])
def test_memory_working_storage_requires_no_swap(tmp_path: Path, monkeypatch: MonkeyPatch, swap: bool) -> None:
    """
    Prevent decrypted runner files from spilling onto a swap device.

    Args:
        tmp_path (Path): Synthetic tmpfs target.
        monkeypatch (MonkeyPatch): Kernel mount and swap metadata.
        swap (bool): Whether any swap device is active.

    Returns:
        None: Only tmpfs without swap is accepted.
    """
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(protection, "_read", lambda arguments: b'{"filesystems":[{"fstype":"tmpfs","source":"tmpfs"}]}')
    monkeypatch.setattr(
        Path, "read_text", lambda *args, **kwargs: "Filename Type Size Used Priority\n" + ("/swap file 100 0 -1\n" if swap else "")
    )

    if swap:
        with pytest.raises(StorageProtectionError, match="swap"):
            require_protected(tmp_path)
    else:
        require_protected(tmp_path)


def test_private_policy_covers_outputs_and_refuses_unverified_remote_storage(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Recheck private source and alternate output paths without claiming TLS encrypts remote storage.

    Args:
        tmp_path (Path): Managed collection marker and independent output location.
        monkeypatch (MonkeyPatch): Local evidence collector.

    Returns:
        None: Output destinations are inspected and remote storage is rejected before local work.
    """
    (tmp_path / ".witful-protected").touch()
    inspected: list[Path] = []
    monkeypatch.setattr(protection, "require_protected", inspected.append)
    output = tmp_path / "cache/index.sqlite3"
    check_collection(tmp_path, output)
    assert tmp_path in inspected and output in inspected
    inspected.clear()

    with pytest.raises(StorageProtectionError, match="Remote database writes are blocked"):
        check_collection(tmp_path, remote=True)

    assert not inspected


def test_protection_exception_keeps_its_legacy_identity() -> None:
    """
    Preserve existing catch clauses when callers adopt the centralized import.

    Returns:
        None: The old import names the canonical ValueError subclass without wrapping it.
    """
    assert protection.StorageProtectionError is StorageProtectionError
    assert StorageProtectionError.__module__ == "witful.exceptions"
    assert StorageProtectionError.__bases__ == (ValueError,)
