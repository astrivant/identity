"""
Replace reviewed files atomically while preserving recoverable configuration backups.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path


def replace_file(path: Path, content: bytes, *, expected: bytes | None, backup: bool = False) -> Path | None:
    """
    Install validated bytes only if the destination still matches the inspected version.

    Args:
        path (Path): Destination owned by the current user; symlinks are resolved.
        content (bytes): Already validated replacement.
        expected (bytes | None): Inspected contents, or None when the destination must not exist.
        backup (bool): Preserve the exact previous bytes and metadata under an exclusive epoch filename.

    Returns:
        Path | None: Created backup, or None for a new or unchanged destination.

    Raises:
        RuntimeError: The destination changed concurrently or backup verification failed.
    """
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if (path.read_bytes() if path.exists() else None) != expected:
        raise RuntimeError(f"Concurrent edit detected: {path}")

    if content == expected:
        return None

    saved = None

    if backup and expected is not None:
        saved = path.with_name(f"{path.stem}.{int(time.time())}{path.suffix}")

        # Exclusive creation preserves earlier backups, even when two edits share a clock second.
        try:
            descriptor = os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            saved = path.with_name(f"{path.stem}.{time.time_ns()}{path.suffix}")
            descriptor = os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)

        with os.fdopen(descriptor, "wb") as stream:
            stream.write(expected)

        shutil.copystat(path, saved)

        if saved.read_bytes() != expected:
            raise RuntimeError(f"Backup verification failed: {saved}")

    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    staging = Path(temporary)

    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

        if expected is not None:
            shutil.copystat(path, staging)

        if (path.read_bytes() if path.exists() else None) != expected:
            raise RuntimeError(f"Concurrent edit detected: {path}")

        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)

    return saved
