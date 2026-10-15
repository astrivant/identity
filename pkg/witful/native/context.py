"""
Separate immutable record identity from current authorization and randomized representations.
"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from attrs import frozen

from witful.exceptions import NativeError

__all__ = ["Context", "identifier", "signature_input"]


def identifier(value: str) -> str:
    """
    Require a canonical opaque UUID without reflecting invalid identifiers.

    Args:
        value (str): Untrusted record, scope, ref, generation or operation identifier.

    Returns:
        str: Unchanged canonical UUID.

    Raises:
        NativeError: The identifier is invalid.
    """
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise NativeError("invalid")
    except ValueError:
        raise NativeError("invalid") from None
    return value


@frozen
class Context:
    """
    Bind ciphertext to an expected immutable record rather than trusting metadata supplied by storage.

    Attributes:
        tenant (str): Opaque owner scope.
        identity (str): Opaque collection scope.
        record (str): Immutable logical revision identifier.
        kind (int): Versioned record-kind discriminator, retained inside trusted manifests.
        schema (int): Logical schema version.
        codec (int): Deterministic CBOR profile version.
        hash (int): Semantic digest-domain version.
        envelope (int): Authenticated encryption envelope version.
    """

    tenant: str
    identity: str
    record: str
    kind: int
    schema: int = 1
    codec: int = 1
    hash: int = 1
    envelope: int = 1

    def __attrs_post_init__(self) -> None:
        """
        Refuse unsupported formats and coercible identifiers before any key-service call.

        Returns:
            None: This immutable context belongs to the supported contract.

        Raises:
            NativeError: An identifier, kind or version is invalid or unsupported.
        """
        for value in (self.tenant, self.identity, self.record):
            identifier(value)
        if type(self.kind) is not int or not 1 <= self.kind <= 65535:
            raise NativeError("invalid")
        if any(type(value) is not int or value != 1 for value in (self.schema, self.codec, self.hash, self.envelope)):
            raise NativeError("unsupported")

    def data(self) -> dict[str, object]:
        """
        Supply the shared record-context wire contract without access-policy state.

        Returns:
            dict[str, object]: Fresh mapping, with no mutable alias to the frozen context.
        """
        return {
            "tenant": self.tenant,
            "identity": self.identity,
            "record": self.record,
            "kind": self.kind,
            "schema": self.schema,
            "codec": self.codec,
            "hash": self.hash,
            "envelope": self.envelope,
        }

    def aad(self) -> bytes:
        """
        Match the maintained broker's versioned immutable context contract exactly.

        Returns:
            bytes: Domain-separated canonical associated data, independent of the current grant and epoch.
        """
        return b"agent-broker-record-v1\x00" + json.dumps(self.data(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def signature_input(context: Context, digest: bytes) -> bytes:
    """
    Construct the broker's context-bound ciphertext-signature message for independent verification.

    Args:
        context (Context): Independently expected record context.
        digest (bytes): SHA-256 of final envelope bytes excluding its signature field.

    Returns:
        bytes: Domain-separated signing message; never a plaintext record digest.
    """
    return b"agent-broker-sign-v1\x00" + hashlib.sha256(context.aad()).digest() + digest
