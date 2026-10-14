"""
Create or reuse dedicated encryption and signing identities with restricted local backups.
"""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives import serialization

from witful.collection.crypto import fingerprint
from witful.collection.models import Config
from witful.collection.process import run

KEY_FILES = ("collection.key", "collection.pub", "collection.password", "cosign.key", "cosign.pub", "cosign.password")


def signing_environment(directory: Path) -> dict[str, str]:
    """
    Scope saved signing credentials to child Cosign commands without modifying the parent environment.

    Args:
        directory (Path): Private backup directory.

    Returns:
        dict[str, str]: Environment with only the two required signing credentials added.
    """
    return {
        **os.environ,
        "COSIGN_PRIVATE_KEY": (directory / "cosign.key").read_text(),
        "COSIGN_PASSWORD": (directory / "cosign.password").read_text(),
    }


def prepare(directory: Path, repository: str) -> Config:
    """
    Generate keys once, then validate every component before any remote secret changes.

    Args:
        directory (Path): Dedicated backup directory, never inside the Git checkout or collection.
        repository (str): Explicit private destination.

    Returns:
        Config: Repository binding and independently computed trust pins.

    Raises:
        ValueError: Existing key material is partial, mismatched, or not privately permissioned.
    """
    if not directory.exists():
        directory.mkdir(parents=True, mode=0o700)
        print(f"Key backup directory: {directory}")

        # Only temporary files contain unencrypted private keys; backups retain encrypted keys and passwords.
        with TemporaryDirectory(prefix="witful-key-", dir=directory) as temporary:
            plain = Path(temporary)
            run(["ssh-keygen", "-q", "-t", "rsa", "-b", "3072", "-m", "PEM", "-N", "", "-C", "witful", "-f", str(plain / "rsa")])
            key = serialization.load_pem_private_key((plain / "rsa").read_bytes(), password=None)
            password = os.urandom(32).hex().encode()
            (directory / "collection.key").write_bytes(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.BestAvailableEncryption(password),
                )
            )
            (directory / "collection.pub").write_bytes(
                key.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            (directory / "collection.password").write_bytes(password)
            (directory / "cosign.password").write_text(os.urandom(32).hex())
            env = {**os.environ, "COSIGN_PASSWORD": (directory / "cosign.password").read_text()}
            run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(plain / "ec")])
            run(["cosign", "import-key-pair", "--key", str(plain / "ec"), "--output-key-prefix", str(directory / "cosign")], env=env)

        for name in KEY_FILES:
            (directory / name).chmod(0o600)

    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError("Key backup directory must be private (0700) and not a symlink")

    for name in KEY_FILES:
        path = directory / name

        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise ValueError("Key backup is incomplete or not private; restore the complete original backup")

    private = serialization.load_pem_private_key(
        (directory / "collection.key").read_bytes(),
        password=(directory / "collection.password").read_bytes(),
    )
    derived = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    signing = run(["cosign", "public-key", "--key", "env://COSIGN_PRIVATE_KEY"], env=signing_environment(directory))

    if fingerprint(derived) != fingerprint((directory / "collection.pub").read_bytes()):
        raise ValueError("Encryption backup key pair does not match")
    if fingerprint(signing) != fingerprint((directory / "cosign.pub").read_bytes()):
        raise ValueError("Signing backup key pair does not match")

    return Config(repository, fingerprint(derived), fingerprint(signing))


def project(directory: Path, repository: str) -> None:
    """
    Install dedicated repository Actions secrets using stdin, retaining keys for resumable setup.

    Args:
        directory (Path): Complete validated key backup.
        repository (str): Explicit private destination.

    Returns:
        None: All repository secrets are updated; partial failures retain the local identity for retry.
    """
    mapping = {
        "WITFUL_COLLECTION_PRIVATE_KEY": "collection.key",
        "WITFUL_COLLECTION_PUBLIC_KEY": "collection.pub",
        "WITFUL_COLLECTION_KEY_PASSWORD": "collection.password",
        "WITFUL_COLLECTION_SIGNING_KEY": "cosign.key",
        "WITFUL_COLLECTION_SIGNING_PASSWORD": "cosign.password",
    }

    for secret, filename in mapping.items():
        run(["gh", "secret", "set", secret, "--repo", repository], data=(directory / filename).read_bytes())

    # A separate Actions secret pins the signing identity independently of files downloaded from Git.
    trusted = fingerprint((directory / "cosign.pub").read_bytes()).encode()
    run(["gh", "secret", "set", "WITFUL_COLLECTION_SIGNING_FINGERPRINT", "--repo", repository], data=trusted)
