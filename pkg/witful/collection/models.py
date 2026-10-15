"""
Define closed transport and repository configuration contracts for private collections.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import TYPE_CHECKING, Literal

from attrs import frozen
from jsonschema import ValidationError

from witful.exceptions import CollectionConfigurationError
from witful.knowledge.contracts import structure

if TYPE_CHECKING:
    from pathlib import Path

MAX_BYTES = 32 * 1024 * 1024
CONFIG = ".config/collection.json"
SOURCE = "collection/sources.enc.json"
FIGURES = "collection/figures.enc.json"


@frozen
class Config:
    """
    Bind one private repository to independently pinned signing and encryption keys.

    Attributes:
        repository (str): Exact owner/repository authorized to receive encrypted records.
        encryption_fingerprint (str): SHA-256 of the RSA encryption public key in DER form.
        signing_fingerprint (str): SHA-256 of the Cosign verification public key in DER form.
        publish_figures (bool): Explicit permission to store readable plots in private Git history.
        version (Literal[1]): Supported configuration version.
        managed_files (tuple[str, ...]): Reviewed opaque file identifiers, separate from the source archive allowlist.
        rotate_by (str | None): UTC date after which new protected writes require replacement keys.
    """

    repository: str
    encryption_fingerprint: str
    signing_fingerprint: str
    publish_figures: bool = False
    version: Literal[1] = 1
    managed_files: tuple[str, ...] = ()
    rotate_by: str | None = None


@frozen
class Envelope:
    """
    Carry bounded authenticated ciphertext without revealing source names or contents.

    Attributes:
        repository (str): Repository bound into authenticated additional data.
        purpose (Literal["sources", "figures", "files"]): Prevents substituting derived output or opaque files for sources.
        encryption_fingerprint (str): Required RSA recipient identity.
        wrapped_key (str): Base64 RSA-OAEP-SHA256 encrypted random AES key.
        nonce (str): Base64 random 96-bit AES-GCM nonce.
        ciphertext (str): Base64 authenticated payload, including the GCM tag.
        version (Literal[1]): Supported wire format.
    """

    repository: str
    purpose: Literal["sources", "figures", "files"]
    encryption_fingerprint: str
    wrapped_key: str
    nonce: str
    ciphertext: str
    version: Literal[1] = 1


def load_config(root: Path) -> Config:
    """
    Validate the configured destination and trust pins before any credential use.

    Args:
        root (Path): Existing private copy of the library repository.

    Returns:
        Config: Validated closed configuration.

    Raises:
        ValueError: Repository identity or fingerprints are not usable.
    """
    return parse_config((root / CONFIG).read_bytes())


def parse_config(data: bytes) -> Config:
    """
    Validate configuration bytes from either an immutable Git index or a working snapshot.

    Args:
        data (bytes): Exact configuration bytes owned by the inspected snapshot.

    Returns:
        Config: Closed configuration with safe ownership paths, trust pins and policy date.

    Raises:
        ValueError: Repository, fingerprints, managed identifiers or deadline are invalid.
    """
    # Schema errors retain the complete input object; translate them at the shared boundary.
    try:
        config = structure(json.loads(data), Config)
    except (ValueError, UnicodeError, ValidationError, RecursionError):
        raise CollectionConfigurationError("Invalid collection configuration (collection-config-invalid)") from None

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", config.repository):
        raise ValueError("Configure an explicit owner/repository")
    if config.repository.lower() == "astrivant/identity":
        raise ValueError("Personal collections cannot target the public library repository")
    if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in (config.encryption_fingerprint, config.signing_fingerprint)):
        raise ValueError("Configure both trusted public-key fingerprints")
    if len(config.managed_files) > 64 or len(set(config.managed_files)) != len(config.managed_files):
        raise ValueError("Use at most 64 unique managed file identifiers")
    for name in config.managed_files:
        file_path(name)
    if config.rotate_by is not None:
        try:
            canonical_date = date.fromisoformat(config.rotate_by).isoformat()
        except ValueError:
            raise CollectionConfigurationError("Invalid collection rotation deadline (collection-config-invalid)") from None
        if canonical_date != config.rotate_by:
            raise CollectionConfigurationError("Invalid collection rotation deadline (collection-config-invalid)")

    return config


def file_path(name: str) -> str:
    """
    Restrict opaque managed names to one non-sensitive path component.

    Args:
        name (str): Reviewed identifier, not the original private filename.

    Returns:
        str: Safe relative envelope path.

    Raises:
        ValueError: The identifier contains unsupported characters or length.
    """
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
        raise ValueError("Managed file names must be short lowercase opaque identifiers")
    return f"collection/files/{name}.enc.json"
