"""
Supply independent synthetic key custody for protected-record tests.
"""

from __future__ import annotations

import hashlib
from typing import Literal
from uuid import uuid4

import pytest
from attrs import field, frozen
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa
from witful.exceptions import NativeError
from witful.native.context import Context, signature_input
from witful.native.envelope import EnvelopeService, Signer


@frozen
class Keys:
    """
    Retain test-only private keys and observable custody calls outside the encrypted store.

    Attributes:
        wrapping (dict[str, rsa.RSAPrivateKey]): Generated wrapping generations.
        signing (dict[str, ed25519.Ed25519PrivateKey]): Independently generated signing generations.
        calls (list[str]): Action names without sensitive values.
    """

    wrapping: dict[str, rsa.RSAPrivateKey] = field(repr=False)
    signing: dict[str, ed25519.Ed25519PrivateKey] = field(repr=False)
    calls: list[str] = field(factory=list)

    def invoke(self, action: Literal["wrap", "unwrap", "sign"], generation: str, context: Context, payload: bytes) -> bytes:
        """
        Execute maintained primitives without filesystem storage or production provider access.

        Args:
            action (Literal["wrap", "unwrap", "sign"]): Requested test key operation.
            generation (str): Test generation identifier.
            context (Context): Expected record context.
            payload (bytes): Transient operation input.

        Returns:
            bytes: Synthetic cryptographic result.

        Raises:
            NativeError: The requested generation is unavailable.
        """
        self.calls.append(action)
        if action == "sign" and generation in self.signing:
            return self.signing[generation].sign(signature_input(context, payload))
        if generation not in self.wrapping:
            raise NativeError("unavailable")
        key = self.wrapping[generation]
        oaep = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=context.aad())
        return key.public_key().encrypt(payload, oaep) if action == "wrap" else key.decrypt(payload, oaep)


@frozen
class Fixture:
    """
    Group synthetic keys, a trusted verifier and immutable record identity.

    Attributes:
        keys (Keys): Independent synthetic custody.
        service (EnvelopeService): Real native sealing and verification implementation.
        context (Context): Random test-only immutable record identifiers.
    """

    keys: Keys
    service: EnvelopeService
    context: Context


@pytest.fixture
def fixture() -> Fixture:
    """
    Generate isolated test-only generations with independently retained trust pins.

    Returns:
        Fixture: A real envelope service without any external secret or database.
    """
    wrapping, signing = str(uuid4()), str(uuid4())
    keys = Keys({wrapping: rsa.generate_private_key(public_exponent=65537, key_size=3072)}, {signing: ed25519.Ed25519PrivateKey.generate()})
    public = keys.signing[signing].public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    trust = {signing: Signer(public, hashlib.sha256(public).hexdigest())}
    service = EnvelopeService(keys, wrapping, signing, trust)
    return Fixture(keys, service, Context(str(uuid4()), str(uuid4()), str(uuid4()), 1))


# Imported fixtures remain shared support, not imports from test case modules.
from tests.native.database import databases as databases  # noqa: E402
from tests.native.runtime import destination as destination  # noqa: E402
from tests.native.runtime import runtime as runtime  # noqa: E402
