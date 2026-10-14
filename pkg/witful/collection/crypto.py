"""
Encrypt bounded collection bytes and verify offline Cosign signatures before decryption.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from witful.collection.models import MAX_BYTES, Envelope
from witful.collection.process import run
from witful.files import replace_file
from witful.knowledge.contracts import as_data, structure
from witful.life.contracts import canonical

if TYPE_CHECKING:
    from witful.collection.models import Config


def fingerprint(public: bytes) -> str:
    """
    Compute a format-independent public key fingerprint.

    Args:
        public (bytes): PEM public key.

    Returns:
        str: SHA-256 of its DER SubjectPublicKeyInfo representation.
    """
    key = serialization.load_pem_public_key(public)
    return hashlib.sha256(key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()


def context(config: Config, purpose: Literal["sources", "figures", "files"]) -> bytes:
    """
    Bind encryption to its intended repository, purpose, format, and recipient.

    Args:
        config (Config): Reviewed repository trust configuration.
        purpose (Literal["sources", "figures", "files"]): Expected data category.

    Returns:
        bytes: Canonical authenticated context.
    """
    return canonical(["witful-collection", 1, config.repository.lower(), purpose, config.encryption_fingerprint])


def encrypt(data: bytes, public: bytes, config: Config, purpose: Literal["sources", "figures", "files"]) -> bytes:
    """
    Use a fresh AES-256 key and nonce for each RSA-wrapped collection snapshot.

    Args:
        data (bytes): Bounded plaintext file map.
        public (bytes): Trusted RSA PEM public key with at least 3072 bits.
        config (Config): Reviewed repository trust configuration.
        purpose (Literal["sources", "figures", "files"]): Data category authenticated with the payload.

    Returns:
        bytes: Canonical JSON envelope suitable for Git and artifact storage.

    Raises:
        ValueError: Data exceeds limits or the configured RSA recipient does not match.
    """
    key = serialization.load_pem_public_key(public)

    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072 or fingerprint(public) != config.encryption_fingerprint:
        raise ValueError("Encryption key does not match the configured RSA recipient")
    if len(data) > MAX_BYTES:
        raise ValueError("Collection exceeds the 32 MiB plaintext limit")

    aad = context(config, purpose)
    symmetric, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    wrapped = key.encrypt(symmetric, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=aad))
    envelope = Envelope(
        config.repository,
        purpose,
        config.encryption_fingerprint,
        base64.b64encode(wrapped).decode(),
        base64.b64encode(nonce).decode(),
        base64.b64encode(AESGCM(symmetric).encrypt(nonce, data, aad)).decode(),
    )
    return canonical(as_data(envelope)) + b"\n"


def decrypt(data: bytes, private: bytes, password: bytes, config: Config, purpose: Literal["sources", "figures", "files"]) -> bytes:
    """
    Authenticate context and ciphertext before returning any private bytes.

    Args:
        data (bytes): Signature-verified encrypted envelope.
        private (bytes): Encrypted RSA PEM private key.
        password (bytes): Exact private key password, supplied through a scoped environment or local backup.
        config (Config): Trusted repository identity and recipient fingerprint.
        purpose (Literal["sources", "figures", "files"]): Required payload category.

    Returns:
        bytes: Authenticated plaintext file map.

    Raises:
        ValueError: Envelope, recipient, purpose, or size is invalid.
        InvalidTag: AES-GCM authentication fails.
    """
    if len(data) > MAX_BYTES * 2:
        raise ValueError("Encrypted collection exceeds the transport limit")

    envelope = structure(json.loads(data), Envelope)
    key = serialization.load_pem_private_key(private, password=password)

    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 3072:
        raise ValueError("Expected a dedicated RSA collection key")

    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    if (envelope.repository, envelope.purpose, envelope.encryption_fingerprint) != (
        config.repository,
        purpose,
        config.encryption_fingerprint,
    ) or fingerprint(public) != config.encryption_fingerprint:
        raise ValueError("Encrypted collection context or key does not match")

    aad = context(config, purpose)
    symmetric = key.decrypt(
        base64.b64decode(envelope.wrapped_key, validate=True),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=aad),
    )
    plain = AESGCM(symmetric).decrypt(
        base64.b64decode(envelope.nonce, validate=True),
        base64.b64decode(envelope.ciphertext, validate=True),
        aad,
    )

    if len(plain) > MAX_BYTES:
        raise ValueError("Decrypted collection exceeds the plaintext limit")

    return plain


def sign(path: Path, env: dict[str, str]) -> None:
    """
    Sign ciphertext locally without sending its digest to public transparency services.

    Args:
        path (Path): Final encrypted envelope.
        env (dict[str, str]): Child environment containing COSIGN_PRIVATE_KEY and COSIGN_PASSWORD.

    Returns:
        None: A key-signed Sigstore bundle accompanies the unchanged ciphertext.
    """
    run(
        [
            "cosign",
            "sign-blob",
            "--yes",
            "--use-signing-config=false",
            "--tlog-upload=false",
            "--key",
            "env://COSIGN_PRIVATE_KEY",
            "--bundle",
            str(path) + ".sigstore.json",
            str(path),
        ],
        env=env,
    )


def verify(path: Path, public: Path, config: Config) -> None:
    """
    Require the pinned signing key and a valid offline signature before processing data.

    Args:
        path (Path): Bounded encrypted envelope to verify.
        public (Path): PEM verification key shipped beside the collection.
        config (Config): Trusted signing fingerprint established at setup.

    Returns:
        None: Ciphertext signature matches the independently pinned public key.

    Raises:
        ValueError: Key, envelope, or signature is invalid.
    """
    if fingerprint(public.read_bytes()) != config.signing_fingerprint or path.stat().st_size > MAX_BYTES * 2:
        raise ValueError("Signing key or envelope does not match the trust configuration")

    run(
        [
            "cosign",
            "verify-blob",
            "--insecure-ignore-tlog",
            "--key",
            str(public),
            "--bundle",
            str(path) + ".sigstore.json",
            str(path),
        ]
    )


def save(root: Path, relative: str, content: bytes, public: bytes, config: Config, env: dict[str, str]) -> None:
    """
    Finalize and verify ciphertext before replacing the committed envelope and verification set.

    Args:
        root (Path): Repository checkout receiving opaque files.
        relative (str): Fixed output path.
        content (bytes): Canonical encrypted bytes.
        public (bytes): Cosign verification key.
        config (Config): Independently trusted key fingerprints.
        env (dict[str, str]): Scoped signing environment.

    Returns:
        None: Verified ciphertext, signature, and checksum are written without plaintext staging.
    """
    with TemporaryDirectory(prefix="witful-seal-") as temporary:
        staged = Path(temporary) / "payload.json"
        staged.write_bytes(content)
        verification = Path(temporary) / "cosign.pub"
        verification.write_bytes(public)
        sign(staged, env)
        verify(staged, verification, config)
        outputs = {
            relative: content,
            relative + ".sigstore.json": Path(str(staged) + ".sigstore.json").read_bytes(),
            relative + ".sha256": (hashlib.sha256(content).hexdigest() + "\n").encode(),
        }

        for name, data in outputs.items():
            path = root / name
            replace_file(path, data, expected=path.read_bytes() if path.exists() else None)
