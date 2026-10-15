"""
Supply independently generated recipient keys for synthetic offline sharing tests.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from witful.native.envelope import EnvelopeService
from witful.native.sharing import PrivateRecipient, Recipient

if TYPE_CHECKING:
    from tests.native.conftest import Fixture


def receiver(fixture: Fixture) -> tuple[Recipient, EnvelopeService]:
    """
    Generate an independent synthetic recipient without sharing any sender private key.

    Args:
        fixture (Fixture): Sender's public trust pins only are reused by the reader.

    Returns:
        tuple[Recipient, EnvelopeService]: Public sender-side recipient and private offline reader.
    """
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    public = private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    recipient = Recipient(str(uuid4()), public, hashlib.sha256(public).hexdigest())
    reader = EnvelopeService(
        PrivateRecipient(recipient.generation, private), recipient.generation, fixture.service.signing, fixture.service.signers
    )
    return recipient, reader
