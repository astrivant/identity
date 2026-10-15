"""
Seal bounded native records before persistence and verify independently pinned ciphertext signatures before decryption.
"""

from __future__ import annotations

import hashlib
import os
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol

from attrs import field, frozen
from cryptography.exceptions import InvalidSignature, InvalidTag, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from witful.exceptions import NativeError
from witful.native import codec
from witful.native.context import Context, identifier, signature_input

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = ["EnvelopeService", "KeyService", "Signer"]


class KeyService(Protocol):
    """
    Keep current authorization and long-lived private keys behind an independently operated service.
    """

    def invoke(self, action: Literal["wrap", "unwrap", "sign"], generation: str, context: Context, payload: bytes) -> bytes:
        """
        Perform one authorized pure key operation without persistent plaintext or implicit retry.

        Args:
            action (Literal["wrap", "unwrap", "sign"]): Explicit key purpose.
            generation (str): Operator-approved key generation.
            context (Context): Immutable expected record identity.
            payload (bytes): Transient data key, wrapped key or ciphertext digest.

        Returns:
            bytes: Transient authorized result.

        Raises:
            NativeError: Current authorization or key custody is unavailable.
        """
        ...


@frozen
class Signer:
    """
    Retain independently reviewed public verification material, never an envelope-supplied trust anchor.

    Attributes:
        public (bytes): DER SubjectPublicKeyInfo containing an Ed25519 public key.
        fingerprint (str): Separately supplied SHA-256 pin of those DER bytes.
    """

    public: bytes = field(repr=False)
    fingerprint: str

    def key(self) -> ed25519.Ed25519PublicKey:
        """
        Verify the public key's independent trust pin before use.

        Returns:
            ed25519.Ed25519PublicKey: Verified signing key.

        Raises:
            NativeError: Key type, encoding or pin is invalid.
        """
        try:
            key = serialization.load_der_public_key(self.public)
            if not isinstance(key, ed25519.Ed25519PublicKey) or hashlib.sha256(self.public).hexdigest() != self.fingerprint:
                raise NativeError("denied")
            return key
        except (ValueError, UnsupportedAlgorithm):
            raise NativeError("denied") from None


def copy_signers(value: Mapping[str, Signer]) -> Mapping[str, Signer]:
    """
    Freeze an independently owned trust map so external mutation cannot replace accepted keys.

    Args:
        value (Mapping[str, Signer]): Reviewed generation-to-signer mapping.

    Returns:
        Mapping[str, Signer]: Read-only copy retaining immutable signer values.
    """
    return MappingProxyType(dict(value))


@frozen
class EnvelopeService:
    """
    Encrypt individual native records with fresh data keys and keep rotation meanings separate.

    Attributes:
        keys (KeyService): Independently authorized wrapping/signing boundary.
        wrapping (str): Generation for new data-key wraps.
        signing (str): Generation for new ciphertext signatures.
        signers (Mapping[str, Signer]): Reviewed accepted historical signer generations; copied at construction.
        limits (codec.Limits): Maximum admitted plaintext record bytes and structural complexity.
        random (Callable[[int], bytes]): Cryptographic randomness boundary, replaceable only for controlled tests.
    """

    keys: KeyService = field(repr=False)
    wrapping: str
    signing: str
    signers: Mapping[str, Signer] = field(converter=copy_signers, repr=False)
    limits: codec.Limits = codec.DEFAULT_LIMITS
    random: Callable[[int], bytes] = field(default=os.urandom, repr=False)

    def __attrs_post_init__(self) -> None:
        """
        Validate selected generations and trusted signer material without a provider call.

        Returns:
            None: Every retained verification generation has a valid independent pin.

        Raises:
            NativeError: An identifier, selected signer or trust pin is invalid.
        """
        identifier(self.wrapping)
        identifier(self.signing)
        if self.signing not in self.signers:
            raise NativeError("denied")
        for generation, signer in self.signers.items():
            identifier(generation)
            signer.key()

    def seal(self, context: Context, value: object) -> bytes:
        """
        Validate, encrypt and sign one record before returning anything eligible for persistence.

        Args:
            context (Context): Immutable caller-owned record context.
            value (object): Closed-domain-validated native value.

        Returns:
            bytes: Authenticated binary envelope with no plaintext metadata or semantic digest.

        Raises:
            NativeError: Encoding, randomness, key access or independent signature verification fails.
        """
        plaintext = codec.encode(value, self.limits)
        data_key, nonce = self.random(32), self.random(12)
        if len(data_key) != 32 or len(nonce) != 12:
            raise NativeError("unavailable")
        wrapped = self.keys.invoke("wrap", self.wrapping, context, data_key)
        ciphertext = AESGCM(data_key).encrypt(nonce, plaintext, context.aad())
        del data_key
        return self.finalize(context, {"v": 1, "w": self.wrapping, "s": self.signing, "n": nonce, "k": wrapped, "c": ciphertext})

    def finalize(self, context: Context, header: dict[str, object]) -> bytes:
        """
        Sign the exact finalized ciphertext header and verify it against independent trust before acceptance.

        Args:
            context (Context): Expected immutable record binding.
            header (dict[str, object]): Complete unsigned encrypted representation.

        Returns:
            bytes: Canonical envelope including its verified signature.

        Raises:
            NativeError: Signing or verification fails.
        """
        payload = codec.encode(header, self.envelope_limits())
        signature = self.keys.invoke("sign", self.signing, context, hashlib.sha256(payload).digest())
        envelope = codec.encode({**header, "signature": signature}, self.envelope_limits())
        self.verify(context, envelope)
        return envelope

    def envelope_limits(self) -> codec.Limits:
        """
        Reserve bounded framing overhead independently of admitted plaintext content.

        Returns:
            codec.Limits: Small fixed-structure envelope with at most an 8 KiB overhead allowance.
        """
        return codec.Limits(bytes=self.limits.bytes + 8192, items=64, depth=4)

    def verify(self, context: Context, envelope: bytes) -> dict[str, object]:
        """
        Authenticate the expected context and ciphertext before any private-key or decryption request.

        Args:
            context (Context): Context from an authorized immutable manifest, never inferred from storage.
            envelope (bytes): Untrusted stored representation.

        Returns:
            dict[str, object]: Closed authenticated header, without its signature.

        Raises:
            NativeError: Envelope structure, key pin, signature or context is invalid.
        """
        try:
            decoded = codec.decode(envelope, self.envelope_limits())
            if not isinstance(decoded, dict) or set(decoded) != {"v", "w", "s", "n", "k", "c", "signature"}:
                raise NativeError("invalid")
            value = {str(key): item for key, item in decoded.items()}
            if type(value["v"]) is not int or value["v"] != 1:
                raise NativeError("unsupported")
            for name in ("w", "s"):
                generation = value[name]
                if not isinstance(generation, str):
                    raise NativeError("invalid")
                identifier(generation)
            for name, minimum, maximum in (("n", 12, 12), ("k", 384, 1024), ("c", 17, self.limits.bytes + 16), ("signature", 64, 64)):
                payload = value[name]
                if not isinstance(payload, bytes) or not minimum <= len(payload) <= maximum:
                    raise NativeError("invalid")
            generation = value["s"]
            signature = value.pop("signature")
            if not isinstance(generation, str) or not isinstance(signature, bytes) or generation not in self.signers:
                raise NativeError("denied")
            digest = hashlib.sha256(codec.encode(value, self.envelope_limits())).digest()
            self.signers[generation].key().verify(signature, signature_input(context, digest))
            return value
        except (InvalidSignature, ValueError):
            raise NativeError("denied") from None

    def _decrypt(self, context: Context, header: dict[str, object]) -> tuple[bytes, object]:
        """
        Recover a transient data key only after ciphertext verification, then authenticate the entire record.

        Args:
            context (Context): Independently expected immutable context.
            header (dict[str, object]): Already verified closed envelope header.

        Returns:
            tuple[bytes, object]: Transient data key and decoded value, both restricted to the trusted process.

        Raises:
            NativeError: Provider, data key, authenticated ciphertext or payload codec is invalid.
        """
        generation, wrapped, nonce, ciphertext = header["w"], header["k"], header["n"], header["c"]
        if (
            not isinstance(generation, str)
            or not isinstance(wrapped, bytes)
            or not isinstance(nonce, bytes)
            or not isinstance(ciphertext, bytes)
        ):
            raise NativeError("invalid")
        data_key = self.keys.invoke("unwrap", generation, context, wrapped)
        if len(data_key) != 32:
            raise NativeError("unavailable")
        try:
            plaintext = AESGCM(data_key).decrypt(nonce, ciphertext, context.aad())
            return data_key, codec.decode(plaintext, self.limits)
        except (InvalidTag, ValueError):
            raise NativeError("denied") from None

    def open(self, context: Context, envelope: bytes) -> object:
        """
        Verify before decrypting and return one authorized native value.

        Args:
            context (Context): Expected context obtained through current authorization.
            envelope (bytes): Stored encrypted record.

        Returns:
            object: Decoded value for subsequent closed-domain validation; never persisted by this method.
        """
        data_key, value = self._decrypt(context, self.verify(context, envelope))
        del data_key
        return value

    def rewrap(self, context: Context, envelope: bytes) -> bytes:
        """
        Replace wrapping/signing generations while retaining the exact authenticated ciphertext and nonce.

        Args:
            context (Context): Original immutable context retained across representations.
            envelope (bytes): Original historical representation, preserved by the caller.

        Returns:
            bytes: Newly signed representation under current wrapping/signing generations.
        """
        header = self.verify(context, envelope)
        data_key, value = self._decrypt(context, header)
        del value
        wrapped = self.keys.invoke("wrap", self.wrapping, context, data_key)
        del data_key
        return self.finalize(context, {**header, "w": self.wrapping, "s": self.signing, "k": wrapped})

    def resign(self, context: Context, envelope: bytes) -> bytes:
        """
        Replace only the signing generation after verifying the historical signature.

        Args:
            context (Context): Unchanged immutable context.
            envelope (bytes): Original representation retained by the caller.

        Returns:
            bytes: New signature over unchanged ciphertext, nonce and wrapped data key; no decryption is requested.
        """
        return self.finalize(context, {**self.verify(context, envelope), "s": self.signing})

    def reseal(self, context: Context, envelope: bytes) -> bytes:
        """
        Create a fresh content key, nonce and ciphertext after authenticating the retained original.

        Args:
            context (Context): Unchanged immutable logical record identity.
            envelope (bytes): Historical encrypted representation.

        Returns:
            bytes: Fresh encrypted representation; persistence must retain an explicit mapping to the original.
        """
        return self.seal(context, self.open(context, envelope))
