"""
Authenticate and decrypt managed artifacts in memory before allowing local publication.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from witful.collection import archive
from witful.collection.managed import PINS, PUBLIC, RECEIPT, SUFFIXES
from witful.collection.material import read_keys
from witful.collection.models import CONFIG, FIGURES, MAX_BYTES, SOURCE, file_path, parse_config
from witful.collection.rotation import verify_snapshot
from witful.exceptions import ArtifactGateError
from witful.privacy.scanner import validate_envelope

if TYPE_CHECKING:
    from collections.abc import Sequence

    from witful.collection.gate.git import Snapshot
    from witful.collection.material import Material


class Checker:
    """
    Reuse immutable verification results across one bounded history inspection.

    Attributes:
        directories (Sequence[Path]): Independently retained original and historical key backups.
        keys (dict[tuple[str, str, str], Material]): Validated key generations, loaded only when artifacts exist.
        verified (set[tuple[tuple[str, str, str], ...]]): Previously authenticated complete artifact snapshots.
    """

    directories: Sequence[Path]
    keys: dict[tuple[str, str, str], Material]
    verified: set[tuple[tuple[str, str, str], ...]]

    def __init__(self, directories: Sequence[Path]) -> None:
        """
        Keep external key locations separate from repository-controlled configuration.

        Args:
            directories (Sequence[Path]): Explicit operator-selected existing backups, never generated here.
        """
        self.directories = directories
        self.keys = {}
        self.verified = set()

    def check(self, tree: Snapshot) -> int:
        """
        Validate policy and artifacts from one snapshot without materializing plaintext sources.

        Args:
            tree (Snapshot): Exact staged or committed file inventory.

        Returns:
            int: Number of authenticated encrypted payloads; zero for ordinary public source.
        """
        names = set(tree.entries)
        # Source records and runtime state have no readable publication exception.
        if any(
            (archive.allowed(name) and not name.startswith("knowledge/schemas/"))
            or name in {"lessons.sqlite3", "lessons.sqlite3-wal", "lessons.sqlite3-shm"}
            or name.startswith(".witful/")
            or (name.startswith("knowledge/") and not name.startswith("knowledge/schemas/"))
            for name in names
        ):
            raise ArtifactGateError("Tracked plaintext collection records must be removed from the publication snapshot")
        artifacts = {name for name in names if name.startswith("collection/")}
        figures = {name for name in names if name.startswith("docs/collection/")}
        if CONFIG not in names:
            if artifacts or figures:
                raise ArtifactGateError("Publication artifacts require collection configuration in the same Git snapshot")
            return 0
        config = parse_config(tree.read(CONFIG, 262144))
        if figures or config.publish_figures:
            raise ArtifactGateError("Personal figures must be encrypted before publication; use an explicit decrypted export for sharing")
        payloads = {SOURCE, *(file_path(name) for name in config.managed_files)}
        if FIGURES in names:
            payloads.add(FIGURES)
        expected = {PUBLIC, *(name + suffix for name in payloads for suffix in SUFFIXES)}
        if PINS in names:
            expected.add(PINS)
        if RECEIPT in names:
            expected.update(RECEIPT + suffix for suffix in SUFFIXES)
        if artifacts != expected:
            raise ArtifactGateError("Managed artifact inventory or verification sidecars are missing or unexpected")
        selected = sorted(expected | {CONFIG})
        binding = tuple((name, *tree.entries[name]) for name in selected)
        if binding in self.verified:
            return len(payloads)

        # Independent backups establish both identities; self-consistent repository pins alone are insufficient.
        identity = (config.repository, config.encryption_fingerprint, config.signing_fingerprint)
        if identity not in self.keys:
            for directory in self.directories:
                location = directory.expanduser()
                if location.resolve().is_relative_to(tree.root.resolve()):
                    raise ArtifactGateError("Keep the independently trusted key backup outside the publication checkout")
                keys = read_keys(location)
                trusted = keys.validate(config.repository)
                self.keys[(trusted.repository, trusted.encryption_fingerprint, trusted.signing_fingerprint)] = keys
        if identity not in self.keys:
            raise ArtifactGateError(
                "Supply --key-dir with the matching retained encryption and signing keys, including historical generations"
            )
        contents: dict[str, bytes] = {}
        total = 0
        for name in selected:
            data = tree.read(name, MAX_BYTES * 2 if name in payloads else 262144)
            total += len(data)
            if total > 256 * 1024 * 1024:
                raise ArtifactGateError("Publication snapshot exceeds its aggregate byte limit")
            if name in payloads:
                validate_envelope(data)
            contents[name] = data

        # Only validated envelopes and public verification metadata touch temporary files.
        # The existing verifier authenticates signatures/checksums and AES-GCM in memory; no plaintext export occurs.
        with tempfile.TemporaryDirectory(prefix="witful-artifact-check-") as temporary:
            root = Path(temporary)
            for name, data in contents.items():
                path = root / name
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.write_bytes(data)
                path.chmod(0o600)
            verify_snapshot(root, self.keys[identity])
        self.verified.add(binding)
        return len(payloads)
