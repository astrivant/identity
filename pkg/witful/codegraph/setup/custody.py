"""
Provision broker-compatible vault keys and persist only their public pins and stable references.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from attrs import frozen
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from witful.codegraph.setup.onepassword import OnePassword, fields, identifier, mapping, text
from witful.exceptions import SetupError

if TYPE_CHECKING:
    from pathlib import Path

    from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes


@frozen
class Key:
    """
    Retain only the non-secret contract needed by the separately deployed broker and client.

    Attributes:
        generation (str): Stable opaque key generation UUID.
        reference (str): Stable 1Password private-key field reference.
        public (str): Base64 public DER SubjectPublicKeyInfo.
        fingerprint (str): SHA-256 of the public DER bytes.
    """

    generation: str
    reference: str
    public: str
    fingerprint: str


def inspect(item: dict[str, object], vault: str, kind: Literal["wrapping", "signing"], field: str = "credential") -> Key:
    """
    Verify the saved key's algorithm, generation and public identity without exposing private bytes.

    Args:
        item (dict[str, object]): Captured existing or newly created vault item.
        vault (str): Selected stable vault ID.
        kind (Literal["wrapping", "signing"]): Broker purpose and required algorithm.
        field (str): Selected private-key field.

    Returns:
        Key: Validated public metadata.

    Raises:
        SetupError: Encoding, algorithm, purpose or generation is invalid.
    """
    values = fields(item)
    try:
        generation = text(values.get("generation"))
        if str(UUID(generation)) != generation or values.get("kind") != kind:
            raise ValueError
        encoded = text(values.get(field))
        if len(encoded) > 32 * 1024:
            raise ValueError
        private = serialization.load_der_private_key(base64.b64decode(encoded, validate=True), None)
        wrapping = isinstance(private, rsa.RSAPrivateKey) and 3072 <= private.key_size <= 8192 and kind == "wrapping"
        signing = isinstance(private, ed25519.Ed25519PrivateKey) and kind == "signing"
        if not (wrapping or signing):
            raise ValueError
        public = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise SetupError(
            "Invalid broker key. Expected dedicated RSA wrapping or Ed25519 signing PKCS8 DER and generation/kind fields."
        ) from None
    return Key(
        generation,
        f"op://{vault}/{identifier(item.get('id'))}/{field}",
        base64.b64encode(public).decode(),
        hashlib.sha256(public).hexdigest(),
    )


def key(provider: OnePassword, vault: str, kind: Literal["wrapping", "signing"], provision: bool, reference: str | None) -> Key:
    """
    Reuse the selected generation or create one broker-compatible key with system-backed randomness.

    Args:
        provider (OnePassword): Authenticated operator CLI.
        vault (str): Selected dedicated vault.
        kind (Literal["wrapping", "signing"]): Separate cryptographic purpose.
        provision (bool): Whether a missing key may be generated and stored.
        reference (str | None): Explicit existing field reference.

    Returns:
        Key: Verified metadata; no private key is written locally.

    Raises:
        SetupError: An existing key is missing while provisioning is disabled.
    """
    field = "credential"
    title = "Witful CodeGraph " + kind
    item: dict[str, object] | None
    if reference is not None:
        item, field = provider.existing(reference, vault)
    else:
        item = provider.find(vault, title)
    if item is None:
        if not provision:
            raise SetupError("Broker key is missing and provisioning is disabled.")
        private: PrivateKeyTypes
        # Ed25519 has a fixed key size. RSA wrapping retains the released wire contract and uses its maximum supported size.
        private = (
            rsa.generate_private_key(public_exponent=65537, key_size=8192) if kind == "wrapping" else ed25519.Ed25519PrivateKey.generate()
        )
        encoded = private.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        item = provider.create(
            vault,
            title,
            {"credential": base64.b64encode(encoded).decode(), "generation": str(uuid4()), "kind": kind},
        )
    return inspect(item, vault, kind, field)


def write(path: Path, value: dict[str, object]) -> None:
    """
    Publish an exclusive private metadata receipt, rejecting mismatched prior bindings on retries.

    Args:
        path (Path): Destination within the setup-owned protected directory.
        value (dict[str, object]): Public pins and references only.

    Returns:
        None: A new receipt is durable or the identical existing receipt remains unchanged.

    Raises:
        SetupError: The destination is unsafe, malformed or bound to another setup.
    """
    if path.is_symlink():
        raise SetupError("Setup receipts must not be symlinks.")
    if path.exists():
        if path.stat().st_mode & 0o077 or path.stat().st_size > 64 * 1024:
            raise SetupError("Setup receipt permissions or size require review.")
        try:
            previous: object = json.loads(path.read_bytes())
        except ValueError:
            raise SetupError("Setup receipt is invalid; preserve it for recovery.") from None
        if mapping(previous) != value:
            raise SetupError("Existing setup bindings changed. Review migration or rotation; no receipt was overwritten.")
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def provision(
    provider: OnePassword,
    directory: Path,
    vault: str,
    enabled: bool,
    wrapping_reference: str | None = None,
    signing_reference: str | None = None,
    token_reference: str | None = None,
) -> dict[str, object]:
    """
    Prepare optional custody and return an immutable reference bundle for separate runtime configuration.

    Args:
        provider (OnePassword): Explicit operator account and CLI.
        directory (Path): Locked protected setup directory outside Git.
        vault (str): User-selected vault name or ID.
        enabled (bool): Automatic missing-resource provisioning, enabled by the explicit setup command by default.
        wrapping_reference (str | None): Existing wrapping key field.
        signing_reference (str | None): Existing signing key field.
        token_reference (str | None): Existing read-only service-account token field.

    Returns:
        dict[str, object]: Public custody references, never private keys or the token.
    """
    from witful.knowledge.contracts import as_data

    selected = provider.vault(vault, enabled)
    keys: dict[str, object] = {}
    for kind, reference in (("wrapping", wrapping_reference), ("signing", signing_reference)):
        # Preserve each verified generation before the next remote mutation. A changed pin cannot be accepted silently on retry.
        purpose: Literal["wrapping", "signing"] = "wrapping" if kind == "wrapping" else "signing"
        metadata = as_data(key(provider, selected, purpose, enabled, reference))
        write(directory / (kind + ".json"), metadata)
        keys[kind] = metadata
    token = provider.token(selected, directory / "service-account.pending", enabled, token_reference)
    result: dict[str, object] = {
        "account": provider.account,
        "vault": selected,
        "keys": keys,
        "service_account_reference": token,
    }
    write(directory / "custody-references.json", result)
    return result
