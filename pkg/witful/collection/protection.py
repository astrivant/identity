"""
Require observable storage encryption or nonswappable memory for private working files.
"""

from __future__ import annotations

import json
import platform
import plistlib
import subprocess
from pathlib import Path

from witful.exceptions import StorageProtectionError

__all__ = ["StorageProtectionError", "check_collection", "require_protected"]


def _read(arguments: list[str]) -> bytes:
    """
    Read bounded host metadata without exposing paths or provider responses on failure.

    Args:
        arguments (list[str]): Fixed system utility and literal path arguments.

    Returns:
        bytes: Successful machine-readable utility output.

    Raises:
        StorageProtectionError: The operating system cannot provide the required evidence.
    """
    try:
        result = subprocess.run(arguments, check=False, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise StorageProtectionError("Storage encryption could not be verified on this host.") from None

    if result.returncode:
        raise StorageProtectionError("Storage encryption could not be verified on this host.")

    return result.stdout


def _encrypted_device(value: object) -> bool:
    """
    Require every backing-device route to cross a device-mapper encryption layer.

    Args:
        value (object): One lsblk inverse-tree node.

    Returns:
        bool: All physical backing paths are protected by an observable crypt mapping.
    """
    if not isinstance(value, dict):
        return False
    if value.get("type") == "crypt":
        return True

    children = value.get("children")
    return isinstance(children, list) and bool(children) and all(_encrypted_device(child) for child in children)


def require_protected(path: Path) -> None:
    """
    Fail closed before private data is written to an unverified working volume.

    Args:
        path (Path): Existing path or future destination on the checked filesystem.

    Returns:
        None: macOS reports FileVault, Linux reports encrypted block ancestry, or RAM storage has no active swap.

    Raises:
        StorageProtectionError: Encryption is absent, unsupported, or unverifiable. Remote database storage cannot be inferred.
    """
    location = path.expanduser().resolve()

    # Inspect the nearest existing parent without creating anything on an unknown volume.
    while not location.exists() and location != location.parent:
        location = location.parent

    try:
        if platform.system() == "Darwin":
            # diskutil accepts a device or mount point, not every directory inside an APFS volume.
            mounts = _read(["/bin/df", "-P", str(location)]).decode().splitlines()
            if len(mounts) != 2 or not mounts[1].split() or not mounts[1].split()[0].startswith("/dev/"):
                raise StorageProtectionError("The working path does not resolve to an inspectable local device.")
            device = mounts[1].split()[0]
            information: object = plistlib.loads(_read(["/usr/sbin/diskutil", "info", "-plist", device]))

            if isinstance(information, dict) and information.get("FileVault") is True:
                return
        elif platform.system() == "Linux":
            mount_information: object = json.loads(_read(["findmnt", "--json", "--target", str(location), "--output", "FSTYPE,SOURCE"]))

            if (
                not isinstance(mount_information, dict)
                or not isinstance(mount_information.get("filesystems"), list)
                or len(mount_information["filesystems"]) != 1
            ):
                raise StorageProtectionError("Working filesystem metadata is incomplete.")

            mount = mount_information["filesystems"][0]

            if not isinstance(mount, dict):
                raise StorageProtectionError("Working filesystem metadata is invalid.")

            if mount.get("fstype") in {"tmpfs", "ramfs"}:
                if len(Path("/proc/swaps").read_text().splitlines()) == 1:
                    return
                raise StorageProtectionError("Memory-backed private processing requires swap to be disabled.")

            source = mount.get("source")

            if isinstance(source, str) and source.startswith("/dev/"):
                devices: object = json.loads(_read(["lsblk", "--json", "--inverse", "--output", "TYPE", "--", source.split("[", 1)[0]]))

                if isinstance(devices, dict):
                    roots = devices.get("blockdevices")

                    if isinstance(roots, list) and roots and all(_encrypted_device(device) for device in roots):
                        return
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        if isinstance(error, StorageProtectionError):
            raise
        raise StorageProtectionError("Storage encryption metadata could not be validated.") from None

    raise StorageProtectionError(
        "Private working storage is not verified as encrypted. Use FileVault or a Linux encrypted volume; "
        "CI may use memory-backed storage with swap disabled. No private data was written by this check."
    )


def check_collection(root: Path, *outputs: Path, remote: bool = False) -> None:
    """
    Enforce the installed private collection's protection policy on ordinary CLI operations.

    Args:
        root (Path): Source collection; unmarked standalone libraries retain their existing storage contract.
        *outputs (Path): Additional cache, export, or database destinations.
        remote (bool): Whether this operation would send records to an external storage service.

    Returns:
        None: Managed private collections use protected source, output, and temporary volumes.

    Raises:
        StorageProtectionError: A private working path is unverified or external at-rest protection is unavailable.
    """
    import tempfile

    if not (root / ".witful-protected").exists() and not (root / ".setup.json").exists():
        return

    # TLS cannot attest to the database host's disks, replicas, or backups. Do not silently weaken the private mode.
    if remote:
        raise StorageProtectionError(
            "Managed private collections cannot verify external storage encryption. Remote database and MCP writes are blocked; "
            "use local encrypted storage until a verified server-side protection contract is available."
        )

    for location in (root, Path(tempfile.gettempdir()), *outputs):
        require_protected(location)
