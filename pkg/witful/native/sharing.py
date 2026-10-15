"""
Create recipient-only disclosures while retaining exact historical ciphertext and independently verified sender provenance.
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from attrs import evolve, field, frozen
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from witful.exceptions import NativeError
from witful.native.backup import Archive, inspect
from witful.native.context import Context, identifier
from witful.native.models import parse
from witful.native.service import Budget
from witful.native.wire import binary, integer, mapping, sequence, text

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.authority import Access
    from witful.native.envelope import EnvelopeService, KeyService
    from witful.native.service import Service
    from witful.native.views import View

__all__ = ["Disclosure", "PrivateRecipient", "Recipient", "create", "open_disclosure"]

SHARING = 11
DEFAULT_BUDGET = Budget()


def oaep(context: Context) -> padding.OAEP:
    """
    Reuse the native RSA-OAEP context contract without introducing another encryption primitive.

    Args:
        context (Context): Independently selected immutable export identity.

    Returns:
        padding.OAEP: SHA-256 OAEP bound to the complete native associated data.
    """
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=context.aad())


@frozen
class Recipient:
    """
    Pin an explicit public encryption recipient without transferring sender signing authority.

    Attributes:
        generation (str): Explicit UUID identifying this recipient's wrapping generation.
        public (bytes): RSA SubjectPublicKeyInfo DER, never a private key.
        fingerprint (str): Independently reviewed SHA-256 of the DER bytes.
    """

    generation: str
    public: bytes = field(repr=False)
    fingerprint: str

    def key(self) -> rsa.RSAPublicKey:
        """
        Admit only a bounded supported RSA key that matches the independent recipient pin.

        Returns:
            rsa.RSAPublicKey: Verified RSA recipient of at least 3072 and at most 8192 bits.
        """
        identifier(self.generation)
        if len(self.public) > 16 * 1024 or hashlib.sha256(self.public).hexdigest() != self.fingerprint:
            raise NativeError("denied")
        try:
            key = serialization.load_der_public_key(self.public)
            if not isinstance(key, rsa.RSAPublicKey) or not 3072 <= key.key_size <= 8192:
                raise NativeError("denied")
            return key
        except (ValueError, UnsupportedAlgorithm):
            raise NativeError("denied") from None


@frozen
class SendingKeys:
    """
    Redirect only export encryption to a reviewed public recipient and retain broker-owned sender signing.

    Attributes:
        source (KeyService): Sender's currently authorized signing boundary.
        recipient (Recipient): Public encryption recipient selected by the operator.
    """

    source: KeyService = field(repr=False)
    recipient: Recipient

    def invoke(self, action: Literal["wrap", "unwrap", "sign"], generation: str, context: Context, payload: bytes) -> bytes:
        """
        Permit public-key wrapping for this export and delegate signatures to the unchanged sender.

        Args:
            action (Literal["wrap", "unwrap", "sign"]): Explicit cryptographic purpose.
            generation (str): Selected recipient or sender-signing generation.
            context (Context): Expected immutable export context.
            payload (bytes): Transient export data key or signature digest.

        Returns:
            bytes: Recipient-wrapped key or sender signature; decryption is unavailable here.
        """
        if context.kind != SHARING:
            raise NativeError("denied")
        if action == "sign":
            return self.source.invoke(action, generation, context, payload)
        if action != "wrap" or generation != self.recipient.generation:
            raise NativeError("denied")
        return self.recipient.key().encrypt(payload, oaep(context))


@frozen
class PrivateRecipient:
    """
    Hold a recipient's private key only inside its separately protected offline process.

    Attributes:
        generation (str): Expected outer wrapping generation.
        key (rsa.RSAPrivateKey): Locally loaded recipient key, never sent to a controller.
    """

    generation: str
    key: rsa.RSAPrivateKey = field(repr=False)

    def invoke(self, action: Literal["wrap", "unwrap", "sign"], generation: str, context: Context, payload: bytes) -> bytes:
        """
        Decrypt only the separately verified export envelope; sender signing and original broker keys remain unavailable.

        Args:
            action (Literal["wrap", "unwrap", "sign"]): Only unwrap is supported.
            generation (str): Independently expected recipient generation.
            context (Context): Expected sharing envelope context.
            payload (bytes): Recipient-wrapped export data key.

        Returns:
            bytes: Transient export data key after RSA authentication checks.
        """
        if action != "unwrap" or generation != self.generation or context.kind != SHARING or not 3072 <= self.key.key_size <= 8192:
            raise NativeError("denied")
        try:
            return self.key.decrypt(payload, oaep(context))
        except ValueError:
            raise NativeError("denied") from None


@frozen
class CapturedKeys:
    """
    Collect only data keys actually authorized during complete snapshot verification, for encryption inside the disclosure.

    Attributes:
        source (KeyService): Current request's independently authorized custody.
        slots (dict[tuple[Context, str, bytes], bytes]): Transient context/wrapped-key-to-data-key map, never persisted outside encryption.
    """

    source: KeyService = field(repr=False)
    slots: dict[tuple[Context, str, bytes], bytes] = field(factory=dict, init=False, repr=False)

    def invoke(self, action: Literal["wrap", "unwrap", "sign"], generation: str, context: Context, payload: bytes) -> bytes:
        """
        Require current custody for every call and retain the resulting symmetric key only for the encrypted sharing package.

        Args:
            action (Literal["wrap", "unwrap", "sign"]): Only original-record unwrap is permitted during capture.
            generation (str): Historical wrapping generation.
            context (Context): Authenticated immutable record context.
            payload (bytes): Signed original wrapped key.

        Returns:
            bytes: Actual authorized key response without caching an access decision.
        """
        if action != "unwrap":
            raise NativeError("denied")
        key = self.source.invoke(action, generation, context, payload)
        if len(key) != 32:
            raise NativeError("invalid")
        slot = (context, generation, payload)
        if slot in self.slots and self.slots[slot] != key:
            raise NativeError("invalid")
        self.slots[slot] = key
        return key


@frozen
class DisclosedKeys:
    """
    Recover only the original per-record keys explicitly included in a verified encrypted disclosure.

    Attributes:
        slots (dict[tuple[Context, str, bytes], bytes]): Private reader-owned key inventory, independent of every original broker key.
    """

    slots: dict[tuple[Context, str, bytes], bytes] = field(repr=False)

    def invoke(self, action: Literal["wrap", "unwrap", "sign"], generation: str, context: Context, payload: bytes) -> bytes:
        """
        Refuse any request outside the exact exported record and wrapped-key bindings.

        Args:
            action (Literal["wrap", "unwrap", "sign"]): Only reading retained ciphertext is permitted.
            generation (str): Exact original wrapping generation.
            context (Context): Independently reconstructed original context.
            payload (bytes): Exact original wrapped data key.

        Returns:
            bytes: Exported symmetric data key, never an original key-encryption or signing private key.
        """
        if action != "unwrap":
            raise NativeError("denied")
        try:
            return self.slots[(context, generation, payload)]
        except KeyError:
            raise NativeError("incomplete") from None


@frozen
class Disclosure:
    """
    Own a verified offline snapshot without activating, merging or granting access to a live identity.

    Attributes:
        archive (Archive): Original ciphertext transactions and receipts, unchanged byte for byte.
        view (View): Protected in-memory reader using only the recipient's disclosed data keys.
        recorded (int): Sender's signed export time, not proof of the live service's current head or revocation state.
    """

    archive: Archive = field(repr=False)
    view: View = field(repr=False)
    recorded: int


def create(service: Service, access: Access, recipient: Recipient | None = None) -> tuple[Context, bytes]:
    """
    Export complete verified native history with recipient-only recovery and unchanged sender signing provenance.

    Args:
        service (Service): Current authenticated native service.
        access (Access): Whole-identity export admission, rechecked before releasing the encrypted result.
        recipient (Recipient | None): Reviewed public recipient override; None uses the active wrapping generation.

    Returns:
        tuple[Context, bytes]: Signed encrypted disclosure; no source private keys or plaintext data keys are released outside it.
    """
    started = service.monotonic()
    registration, _ = service.snapshot(access, "export", "*")
    retained = Archive(access.scope, service.store.history(access.scope))
    if retained.head != registration.head:
        raise NativeError("conflict")
    keys = service.keys(access)
    capture = CapturedKeys(keys.keys)
    inspect(retained, evolve(keys, keys=capture), service.budget, service.monotonic)
    slots = [
        {"context": context.data(), "generation": generation, "wrapped": wrapped, "key": key}
        for (context, generation, wrapped), key in sorted(
            capture.slots.items(), key=lambda item: (item[0][0].aad(), item[0][1], item[0][2])
        )
    ]
    context = Context(access.scope.tenant, access.scope.identity, str(uuid4()), SHARING)
    if recipient is not None:
        recipient.key()
        keys = evolve(keys, keys=SendingKeys(keys.keys, recipient), wrapping=recipient.generation)
    payload = {"version": 1, "archive": retained.encode(keys.limits), "keys": slots, "recorded": int(service.clock())}
    sealed = keys.seal(context, payload)
    keys.verify(context, sealed)
    service.release(access, "export", "*", registration, started)
    return context, sealed


def open_disclosure(
    context: Context,
    sealed: bytes,
    keys: EnvelopeService,
    budget: Budget = DEFAULT_BUDGET,
    monotonic: Callable[[], float] = time.monotonic,
) -> Disclosure:
    """
    Verify and read all retained history without the original broker, source database, or sender private keys.

    Args:
        context (Context): Independently expected export identity, not trusted merely because it accompanies the file.
        sealed (bytes): Complete signed encrypted sharing envelope.
        keys (EnvelopeService): Recipient decryption with independently pinned original sender verification generations.
        budget (Budget): Explicit memory and inspection limits.
        monotonic (Callable[[], float]): Elapsed-time boundary for the complete offline operation.

    Returns:
        Disclosure: Fully verified immutable snapshot and protected in-memory reader, with no automatic live import.
    """
    if context.kind != SHARING:
        raise NativeError("denied")
    started = monotonic()
    body = mapping(keys.open(context, sealed), {"version", "archive", "keys", "recorded"})
    if integer(body["version"]) != 1:
        raise NativeError("unsupported")
    retained = Archive.decode(binary(body["archive"]), keys.limits)
    if (retained.scope.tenant, retained.scope.identity) != (context.tenant, context.identity):
        raise NativeError("denied")
    slots: dict[tuple[Context, str, bytes], bytes] = {}
    for item in sequence(body["keys"]):
        value = mapping(item, {"context", "generation", "wrapped", "key"})
        original = parse(value["context"], Context)
        generation, wrapped, key = identifier(text(value["generation"])), binary(value["wrapped"]), binary(value["key"])
        slot = (original, generation, wrapped)
        if (
            (original.tenant, original.identity) != (context.tenant, context.identity)
            or not 384 <= len(wrapped) <= 1024
            or len(key) != 32
            or slot in slots
        ):
            raise NativeError("invalid")
        slots[slot] = key
    disclosed = DisclosedKeys(slots)
    observed = CapturedKeys(disclosed)
    view = inspect(retained, evolve(keys, keys=observed), budget, monotonic)
    if set(observed.slots) != set(slots) or monotonic() - started > budget.seconds:
        raise NativeError("incomplete")
    recorded = integer(body["recorded"])
    if recorded < 0:
        raise NativeError("invalid")
    return Disclosure(retained, view, recorded)
