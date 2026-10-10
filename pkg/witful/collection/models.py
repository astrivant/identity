"""
Define closed transport and repository configuration contracts for private collections.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Literal

from attrs import frozen

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
    """

    repository: str
    encryption_fingerprint: str
    signing_fingerprint: str
    publish_figures: bool = False
    version: Literal[1] = 1


@frozen
class Envelope:
    """
    Carry bounded authenticated ciphertext without revealing source names or contents.

    Attributes:
        repository (str): Repository bound into authenticated additional data.
        purpose (Literal["sources", "figures"]): Prevents substituting derived output for sources.
        encryption_fingerprint (str): Required RSA recipient identity.
        wrapped_key (str): Base64 RSA-OAEP-SHA256 encrypted random AES key.
        nonce (str): Base64 random 96-bit AES-GCM nonce.
        ciphertext (str): Base64 authenticated payload, including the GCM tag.
        version (Literal[1]): Supported wire format.
    """

    repository: str
    purpose: Literal["sources", "figures"]
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
    config = structure(json.loads((root / CONFIG).read_text()), Config)

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", config.repository):
        raise ValueError("Configure an explicit owner/repository")
    if config.repository.lower() == "astrivant/identity":
        raise ValueError("Personal collections cannot target the public library repository")
    if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in (config.encryption_fingerprint, config.signing_fingerprint)):
        raise ValueError("Configure both trusted public-key fingerprints")

    return config
