"""
Define ciphertext-only persistence with one atomic frontier for every logical ref in an identity.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

from attrs import field, frozen

from witful.exceptions import NativeError
from witful.native.context import identifier

__all__ = ["Batch", "Head", "Object", "Scope", "Store"]


@frozen
class Scope:
    """
    Select opaque routing IDs without granting access to the corresponding records.

    Attributes:
        tenant (str): Canonical opaque tenant UUID.
        identity (str): Canonical opaque identity UUID.
    """

    tenant: str
    identity: str

    def __attrs_post_init__(self) -> None:
        """
        Reject malformed routing values before accessing storage.

        Returns:
            None: Both identifiers are canonical.
        """
        identifier(self.tenant)
        identifier(self.identity)


@frozen
class Object:
    """
    Retain an immutable encrypted representation; kind and semantic relationships stay encrypted.

    Attributes:
        id (str): Random representation UUID, never a plaintext content digest.
        payload (bytes): Signed authenticated envelope bytes.
    """

    id: str
    payload: bytes = field(repr=False)

    def __attrs_post_init__(self) -> None:
        """
        Bound persistent input before a driver or Git process handles it.

        Returns:
            None: The opaque object is structurally admissible, not necessarily authentic.
        """
        identifier(self.id)
        if type(self.payload) is not bytes or not self.payload:
            raise NativeError("invalid")

    @property
    def digest(self) -> bytes:
        """
        Fingerprint ciphertext for transport and recovery, independently of semantic hashes.

        Returns:
            bytes: SHA-256 of the exact persistent representation.
        """
        return hashlib.sha256(self.payload).digest()


@frozen
class Head:
    """
    Identify one atomic published frontier, with generation preventing ref ABA.

    Attributes:
        generation (int): Monotonically increasing identity commit watermark.
        root (str | None): Encrypted frontier object, absent only before the first commit.
        digest (bytes): Exact ciphertext digest, empty only for an uninitialized frontier.
    """

    generation: int = 0
    root: str | None = None
    digest: bytes = b""

    def __attrs_post_init__(self) -> None:
        """
        Reject incoherent empty states or malformed nonempty frontier references.

        Returns:
            None: Generation and root agree.
        """
        if type(self.generation) is not int or self.generation < 0:
            raise NativeError("invalid")
        if self.root is None:
            if self.generation != 0 or self.digest:
                raise NativeError("invalid")
        else:
            identifier(self.root)
            if self.generation == 0 or type(self.digest) is not bytes or len(self.digest) != 32:
                raise NativeError("invalid")


@frozen
class Batch:
    """
    Carry already sealed candidate bytes; persistence never calls a key service inside its transaction.

    Attributes:
        operation (str): Stable caller operation UUID.
        expected (Head): Exact previously authorized frontier.
        root (Object): Complete new encrypted multi-ref manifest.
        objects (tuple[Object, ...]): Immutable sealed revisions, including retained original representations.
        receipt (Object): Encrypted request binding and durable outcome, committed with the frontier.
        outbox (tuple[Object, ...]): Encrypted pending projection work, part of the same commit.
    """

    operation: str
    expected: Head
    root: Object
    objects: tuple[Object, ...]
    receipt: Object
    outbox: tuple[Object, ...] = ()

    def __attrs_post_init__(self) -> None:
        """
        Refuse ambiguous object ownership before persistence.

        Returns:
            None: Every immutable ID occurs once in this candidate.
        """
        identifier(self.operation)
        values = (self.root, self.receipt, *self.objects, *self.outbox)
        if len({value.id for value in values}) != len(values):
            raise NativeError("invalid")

    @property
    def target(self) -> Head:
        """
        Derive the exact next frontier from the sealed candidate.

        Returns:
            Head: One generation after the expected state.
        """
        return Head(self.expected.generation + 1, self.root.id, self.root.digest)


class Store(Protocol):
    """
    Persist ciphertext only; callers must use the authority-enforcing service for trusted operations.
    """

    def head(self, scope: Scope) -> Head:
        """
        Read one complete publication boundary.

        Args:
            scope (Scope): Opaque storage partition; not an access grant.

        Returns:
            Head: Current atomic frontier.
        """
        ...

    def get(self, scope: Scope, identifiers: tuple[str, ...]) -> tuple[Object, ...]:
        """
        Fetch an explicitly authorized bounded set, preserving requested order.

        Args:
            scope (Scope): Opaque storage partition.
            identifiers (tuple[str, ...]): Exact immutable representation IDs.

        Returns:
            tuple[Object, ...]: Complete ciphertext set; missing objects fail closed.
        """
        ...

    def receipt(self, scope: Scope, operation: str) -> Object | None:
        """
        Resolve an uncertain transaction without creating another semantic operation.

        Args:
            scope (Scope): Opaque storage partition.
            operation (str): Stable operation UUID.

        Returns:
            Object | None: Committed encrypted receipt, or no observed commit.
        """
        ...

    def commit(self, scope: Scope, batch: Batch) -> Head:
        """
        Atomically publish sealed objects, refs, receipt and outbox under one frontier CAS.

        Args:
            scope (Scope): Admitted scope; external authority must fence the call.
            batch (Batch): Exact precomputed sealed candidate, retained across ambiguous retries.

        Returns:
            Head: Durable target frontier after commit.

        Raises:
            NativeError: Conflict, integrity error, storage outage or uncertain commit.
        """
        ...

    def history(self, scope: Scope) -> tuple[Batch, ...]:
        """
        Export all retained committed transactions in causal order within configured bounds.

        Args:
            scope (Scope): Independently admitted identity partition.

        Returns:
            tuple[Batch, ...]: Complete ciphertext recovery history; overflow is explicit incomplete coverage.
        """
        ...
