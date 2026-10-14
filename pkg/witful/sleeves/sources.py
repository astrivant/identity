"""
Keep per-sleeve plaintext outside Git and reuse the collection's signed encryption boundary.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from witful.collection import archive
from witful.collection.models import CONFIG, SOURCE, load_config
from witful.collection.operations import restore, seal
from witful.exceptions import SleeveError

if TYPE_CHECKING:
    from witful.sleeves.models import Sleeve

TRANSPORT = (SOURCE, SOURCE + ".sigstore.json", SOURCE + ".sha256")


def digest(source: Path) -> str:
    """
    Fingerprint only the allowlisted plaintext locally to detect uncheckpointed work.

    Args:
        source (Path): Private source directory outside the worktree.

    Returns:
        str: Local SHA-256, never copied into a Git commit or remote receipt.
    """
    return hashlib.sha256(archive.pack(source)).hexdigest()


def initialize(sleeve: Sleeve) -> str | None:
    """
    Restore the starting revision into a distinct plaintext workspace when encryption is configured.

    Args:
        sleeve (Sleeve): Newly created worktree and optional existing keys.

    Returns:
        str | None: Initial source fingerprint for encrypted collections.

    Raises:
        SleeveError: Encrypted setup is missing keys or targets a different repository.
    """
    root = Path(sleeve.worktree)

    if not (root / CONFIG).exists():
        return None
    if sleeve.keys is None or load_config(root).repository.lower() != sleeve.repository.lower():
        raise SleeveError("Encrypted sleeves need --key-dir and collection configuration matching the private origin.")

    source = Path(sleeve.directory) / "source"
    restore(root, Path(sleeve.keys), source, "sources")
    archive.validate(source)
    return digest(source)


def validate(sleeve: Sleeve) -> None:
    """
    Validate the committed collection using its actual transport rather than stale local plaintext.

    Args:
        sleeve (Sleeve): Current worktree and key backup reference.

    Returns:
        None: Collection schemas and causal journal contracts pass.

    Raises:
        SleeveError: An encrypted collection has no decryption key reference.
    """
    root = Path(sleeve.worktree)

    if (root / CONFIG).exists():
        if sleeve.keys is None or load_config(root).repository.lower() != sleeve.repository.lower():
            raise SleeveError("The encrypted collection no longer matches its sleeve destination or key setup.")

        with TemporaryDirectory(prefix="witful-sleeve-check-", dir=sleeve.directory) as temporary:
            source = Path(temporary) / "source"
            restore(root, Path(sleeve.keys), source, "sources")
            archive.validate(source)
    elif (root / "knowledge/catalog.json").exists():
        archive.validate(root)


def checkpoint(sleeve: Sleeve) -> tuple[tuple[str, ...], str]:
    """
    Seal the isolated plaintext snapshot into the existing encrypted transport paths.

    Args:
        sleeve (Sleeve): Open encrypted session.

    Returns:
        tuple[tuple[str, ...], str]: Safe staging paths and the exact snapshot fingerprint that was sealed.

    Raises:
        SleeveError: A key reference is missing.
    """
    if sleeve.keys is None:
        raise SleeveError("Encrypted checkpoints require the original key directory.")

    source = Path(sleeve.directory) / "source"

    # Freeze the input once. Later edits must never be marked as backed up by an earlier upload.
    payload = archive.pack(source)
    snapshot_digest = hashlib.sha256(payload).hexdigest()

    if snapshot_digest != sleeve.source_digest:
        with TemporaryDirectory(prefix="witful-checkpoint-", dir=sleeve.directory) as temporary:
            frozen = Path(temporary) / "sources"
            archive.unpack(payload, frozen)
            seal(Path(sleeve.worktree), frozen, Path(sleeve.keys))

    return TRANSPORT, snapshot_digest


def unchanged(sleeve: Sleeve) -> None:
    """
    Prevent closure when ignored plaintext still contains uncheckpointed observations.

    Args:
        sleeve (Sleeve): Current session with a prior source digest.

    Returns:
        None: No allowlisted plaintext change remains unpublished.

    Raises:
        SleeveError: Local source records differ from the last checkpoint.
    """
    if sleeve.keys is not None and sleeve.source_digest is None:
        raise SleeveError("Startup did not finish restoring sources. Restore and checkpoint before closure.")
    if sleeve.source_digest is not None and digest(Path(sleeve.directory) / "source") != sleeve.source_digest:
        raise SleeveError("The sleeve has uncheckpointed plaintext records; checkpoint before finishing.")
