"""
Validate candidate key sets without exposing private material in arguments or diagnostics.
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import TYPE_CHECKING

from attrs import frozen
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from witful.collection.crypto import fingerprint
from witful.collection.keys import prepare
from witful.collection.models import Config
from witful.collection.process import run
from witful.collection.protection import require_protected
from witful.knowledge.contracts import as_data, structure

if TYPE_CHECKING:
    from pathlib import Path


@frozen(repr=False)
class Material:
    """
    Hold one complete key generation in process memory.

    Attributes:
        private (str): Password-encrypted RSA private key.
        public (str): Matching RSA public key.
        password (str): RSA decryption password.
        signing_private (str): Password-encrypted Cosign private key.
        signing_public (str): Matching Cosign public key.
        signing_password (str): Cosign decryption password.
    """

    private: str
    public: str
    password: str
    signing_private: str
    signing_public: str
    signing_password: str

    def environment(self, base: dict[str, str]) -> dict[str, str]:
        """
        Return scoped existing environment names for this generation.

        Args:
            base (dict[str, str]): Explicit inherited process context, copied rather than changed.

        Returns:
            dict[str, str]: Environment for encryption and Cosign children.
        """
        return {
            **base,
            "WITFUL_COLLECTION_PRIVATE_KEY": self.private,
            "WITFUL_COLLECTION_PUBLIC_KEY": self.public,
            "WITFUL_COLLECTION_KEY_PASSWORD": self.password,
            "WITFUL_COLLECTION_SIGNING_FINGERPRINT": fingerprint(self.signing_public.encode()),
            "COSIGN_PRIVATE_KEY": self.signing_private,
            "COSIGN_PASSWORD": self.signing_password,
        }

    def validate(self, repository: str) -> Config:
        """
        Check both private/public pairs before trusting candidate fingerprints.

        Args:
            repository (str): Explicit owning repository.

        Returns:
            Config: Derived encryption and signing identities.

        Raises:
            ValueError: A password, key type, key strength, or pair is invalid.
        """
        key = serialization.load_pem_private_key(self.private.encode(), password=self.password.encode())
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 3072:
            raise ValueError("Expected a dedicated RSA collection key")
        derived = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        if fingerprint(derived) != fingerprint(self.public.encode()):
            raise ValueError("Candidate encryption pair differs")
        signer = run(["cosign", "public-key", "--key", "env://COSIGN_PRIVATE_KEY"], env=self.environment(dict(os.environ)))
        if fingerprint(signer) != fingerprint(self.signing_public.encode()):
            raise ValueError("Candidate signing pair differs")
        return Config(repository, fingerprint(derived), fingerprint(signer))


@frozen(repr=False)
class Candidate:
    """
    Bind a complete candidate secret to its repository and next rotation deadline.

    Attributes:
        repository (str): Exact destination for this key set.
        rotate_by (str): UTC ISO date before which the next rotation is due.
        keys (Material): Separate encryption and signing identities.
    """

    repository: str
    rotate_by: str
    keys: Material


def read_keys(directory: Path) -> Material:
    """
    Load an existing private backup without generating or changing any keys.

    Args:
        directory (Path): Complete existing backup on protected storage.

    Returns:
        Material: Existing key generation.

    Raises:
        ValueError: A backup is missing, symlinked, or readable by other users.
    """
    require_protected(directory)
    if not directory.is_dir() or directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError("Use an existing private key directory")
    names = ("collection.key", "collection.pub", "collection.password", "cosign.key", "cosign.pub", "cosign.password")
    for name in names:
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077 or path.stat().st_size > 16384:
            raise ValueError("Key backup is incomplete or not private")
    return Material(*(directory.joinpath(name).read_text() for name in names))


def read_candidate(value: str, repository: str, today: date) -> Candidate:
    """
    Reject incomplete, expired, or cross-repository candidate secrets before use.

    Args:
        value (str): JSON read from the candidate secret or a protected local file.
        repository (str): Expected destination.
        today (date): Explicit UTC clock boundary.

    Returns:
        Candidate: Fully validated candidate.

    Raises:
        ValueError: Candidate exceeds limits, binds another repository, or needs rotation already.
    """
    if len(value.encode()) > 32768:
        raise ValueError("Candidate key set exceeds the secret size limit")
    candidate = structure(json.loads(value), Candidate)
    deadline = date.fromisoformat(candidate.rotate_by)
    if candidate.repository != repository or deadline.isoformat() != candidate.rotate_by or deadline <= today:
        raise ValueError("Candidate repository or rotation deadline is invalid")
    candidate.keys.validate(repository)
    return candidate


def export_candidate(directory: Path, repository: str, deadline: str, output: Path, today: date) -> None:
    """
    Explicitly create or reuse a separate key backup and write a private upload file.

    Args:
        directory (Path): Dedicated new generation directory, separate from the old backup.
        repository (str): Explicit owning repository.
        deadline (str): Owner-selected future rotation date.
        output (Path): New private JSON file outside Git, never standard output.
        today (date): Explicit UTC clock boundary.

    Returns:
        None: Candidate credentials are retained locally for a separately authorized secret upload.
    """
    require_protected(directory)
    require_protected(output)
    for location in (directory, output):
        if any((parent / ".git").exists() for parent in (location.resolve(), *location.resolve().parents)):
            raise ValueError("Keep key backups and candidate secrets outside Git worktrees")
    if output.exists() or date.fromisoformat(deadline) <= today:
        raise ValueError("Choose a new private output and future deadline")
    prepare(directory, repository)
    value = json.dumps(as_data(Candidate(repository, deadline, read_keys(directory))), sort_keys=True)
    read_candidate(value, repository, today)
    # Exclusive creation cannot silently replace the only candidate or an old backup.
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(value + "\n")
