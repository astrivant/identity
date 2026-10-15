"""
Export and restore complete encrypted native history with independent signature checks and exact receipt preservation.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING
from uuid import uuid4

from attrs import field, frozen

from witful.exceptions import NativeError
from witful.native import codec, domains
from witful.native.context import Context, identifier
from witful.native.derivation_models import validate as validate_derivation
from witful.native.kinds import DERIVATION
from witful.native.models import Frontier, Pointer, Receipt, parse
from witful.native.original_git import GIT_ARCHIVE, Repository
from witful.native.original_git import validate_view as validate_original_git
from witful.native.service import FRONTIER, RECEIPT, Service
from witful.native.storage import Batch, Head, Object, Scope
from witful.native.views import View
from witful.native.wire import binary, decode_batch, encode_batch, integer, mapping, sequence, text

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from witful.native.authority import Access
    from witful.native.envelope import EnvelopeService
    from witful.native.service import Budget
    from witful.native.storage import Store

__all__ = ["Archive", "archive", "inspect", "restore", "verify"]

BACKUP = 6


@frozen
class Archive:
    """
    Hold a bounded immutable recovery package in trusted process memory only.

    Attributes:
        scope (Scope): Authenticated original identity scope.
        batches (tuple[Batch, ...]): Complete original transactions with immutable receipts and outbox bytes.
    """

    scope: Scope
    batches: tuple[Batch, ...] = field(repr=False)

    @property
    def head(self) -> Head:
        """
        Select the exact final retained frontier.

        Returns:
            Head: Last transaction target or the empty state.
        """
        return self.batches[-1].target if self.batches else Head()

    def objects(self) -> dict[str, Object]:
        """
        Validate complete transaction continuity and immutable object identity before any destination mutation.

        Returns:
            dict[str, Object]: Complete opaque object index, built from ciphertext only.
        """
        expected = Head()
        operations: set[str] = set()
        objects: dict[str, Object] = {}
        for batch in self.batches:
            if batch.expected != expected or batch.operation in operations:
                raise NativeError("invalid")
            operations.add(batch.operation)
            for item in (batch.root, batch.receipt, *batch.objects, *batch.outbox):
                if item.id in objects and objects[item.id] != item:
                    raise NativeError("invalid")
                objects[item.id] = item
            expected = batch.target
        return objects

    def encode(self, limits: codec.Limits) -> bytes:
        """
        Serialize only encrypted records and approved opaque metadata for outer authenticated encryption.

        Args:
            limits (codec.Limits): Aggregate archival resource budget.

        Returns:
            bytes: Deterministic versioned recovery bytes, never a plaintext journal export.
        """
        self.objects()
        return codec.encode(
            {
                "v": 1,
                "tenant": self.scope.tenant,
                "identity": self.scope.identity,
                "batches": [encode_batch(batch, limits) for batch in self.batches],
            },
            limits,
        )

    @classmethod
    def decode(cls, payload: bytes, limits: codec.Limits) -> Archive:
        """
        Reject malformed or incomplete recovery history before trusting its target frontier.

        Args:
            payload (bytes): Authenticated decrypted package bytes.
            limits (codec.Limits): Aggregate archival resource budget.

        Returns:
            Archive: Complete structurally validated ciphertext history.
        """
        value = mapping(codec.decode(payload, limits), {"v", "tenant", "identity", "batches"})
        if integer(value["v"]) != 1:
            raise NativeError("unsupported")
        result = cls(
            Scope(text(value["tenant"]), text(value["identity"])),
            tuple(decode_batch(binary(item), limits) for item in sequence(value["batches"])),
        )
        result.objects()
        return result


@frozen
class SnapshotStore:
    """
    Read an independently retained recovery snapshot without mutating a live source or allocating a plaintext database.

    Attributes:
        archive (Archive): Authenticated complete history under review.
    """

    archive: Archive = field(repr=False)
    _objects: Mapping[str, Object] = field(init=False, repr=False)

    def __attrs_post_init__(self) -> None:
        """
        Build one immutable ciphertext index for the independent snapshot reader.

        Returns:
            None: Repeated verification reads reuse validated immutable object bindings.
        """
        object.__setattr__(self, "_objects", MappingProxyType(self.archive.objects()))

    def head(self, scope: Scope) -> Head:
        """
        Require the original identity binding before exposing the recovery frontier.

        Args:
            scope (Scope): Independently expected scope.

        Returns:
            Head: Exact retained frontier.
        """
        if scope != self.archive.scope:
            raise NativeError("denied")
        return self.archive.head

    def get(self, scope: Scope, identifiers: tuple[str, ...]) -> tuple[Object, ...]:
        """
        Read exact immutable ciphertext from the independent snapshot.

        Args:
            scope (Scope): Independently expected scope.
            identifiers (tuple[str, ...]): Exact authorized UUIDs.

        Returns:
            tuple[Object, ...]: Complete requested ciphertext.
        """
        self.head(scope)
        try:
            return tuple(self._objects[item] for item in identifiers)
        except KeyError:
            raise NativeError("incomplete") from None

    def receipt(self, scope: Scope, operation: str) -> Object | None:
        """
        Resolve an exact original receipt in retained history.

        Args:
            scope (Scope): Expected identity scope.
            operation (str): Original operation UUID.

        Returns:
            Object | None: Original encrypted receipt.
        """
        self.head(scope)
        return next((batch.receipt for batch in self.archive.batches if batch.operation == operation), None)

    def history(self, scope: Scope) -> tuple[Batch, ...]:
        """
        Return the complete immutable transaction sequence.

        Args:
            scope (Scope): Expected scope.

        Returns:
            tuple[Batch, ...]: Retained encrypted history.
        """
        self.head(scope)
        return self.archive.batches

    def resolve(self, scope: Scope, operation: str) -> tuple[Head, Object | None]:
        """
        Read an immutable snapshot's already settled frontier and receipt.

        Args:
            scope (Scope): Expected identity scope.
            operation (str): Stable operation UUID.

        Returns:
            tuple[Head, Object | None]: Immutable recovery state.
        """
        return self.head(scope), self.receipt(scope, operation)

    def commit(self, scope: Scope, batch: Batch) -> Head:
        """
        Reject every mutation of a recovery snapshot.

        Args:
            scope (Scope): Requested scope.
            batch (Batch): Candidate that must not alter the archive.

        Returns:
            Head: Never returned; the archive is read-only.
        """
        raise NativeError("denied")


def verify(service: Service, access: Access, archive: Archive) -> None:
    """
    Restore the complete snapshot into an independent reader and validate every retained frontier and selected domain view.

    Args:
        service (Service): Current trusted key and validation boundaries.
        access (Access): Current export or migration admission.
        archive (Archive): Ciphertext history to verify independently of live tables.

    Returns:
        None: Every retained transaction, ref, domain chain, receipt and original representation is authenticated.
    """
    if archive.scope != access.scope:
        raise NativeError("denied")
    inspect(archive, service.keys(access), service.budget, service.monotonic)


def inspect(archive: Archive, keys: EnvelopeService, budget: Budget, monotonic: Callable[[], float]) -> View:
    """
    Verify every retained representation through one reader usable by live recovery and recipient-only offline inspection.

    Args:
        archive (Archive): Complete immutable ciphertext history.
        keys (EnvelopeService): Independently pinned envelope verifier and permitted decryption boundary.
        budget (Budget): Explicit complete-operation resource limits.
        monotonic (Callable[[], float]): Elapsed-time boundary supplied by the caller.

    Returns:
        View: Verified read-only snapshot with every stored object accounted for by an authenticated pointer.
    """
    objects = archive.objects()
    if sum(len(item.payload) for item in objects.values()) > budget.bytes:
        raise NativeError("incomplete")
    started = monotonic()
    view = View(archive.scope, SnapshotStore(archive), keys, budget, monotonic)
    for batch in archive.batches:
        if monotonic() - started > budget.seconds:
            raise NativeError("incomplete")
        frontier = parse(view.open(Pointer(batch.root.id, batch.root.id, FRONTIER, batch.root.digest.hex())), Frontier)
        if len(frontier.refs) > budget.refs or len(frontier.revisions) > budget.revisions:
            raise NativeError("incomplete")
        if len({item.name for item in frontier.refs}) != len(frontier.refs):
            raise NativeError("invalid")
        if len({item.record for item in frontier.revisions}) != len(frontier.revisions):
            raise NativeError("invalid")
        old = batch.expected
        expected_previous = Pointer(old.root, old.root, FRONTIER, old.digest.hex()) if old.root is not None else None
        if frontier.previous != expected_previous:
            raise NativeError("invalid")
        receipt = parse(view.open(Pointer(batch.operation, batch.receipt.id, RECEIPT, batch.receipt.digest.hex())), Receipt)
        if receipt.operation != batch.operation or receipt.generation != batch.target.generation:
            raise NativeError("invalid")
        if receipt.root != Pointer(batch.root.id, batch.root.id, FRONTIER, batch.root.digest.hex()):
            raise NativeError("invalid")
        for pointer in (*frontier.archives, *frontier.outbox):
            value = view.open(pointer)
            if pointer.kind == GIT_ARCHIVE:
                validate_original_git(view, parse(value, Repository))
            elif pointer.kind == DERIVATION:
                validate_derivation(value)
        for pointer in frontier.revisions:
            revision = view.revision(frontier, pointer.record)
            entry = domains.decode(view.open(revision.payload))
            if entry.domain != revision.domain:
                raise NativeError("invalid")
            if revision.source is not None:
                binary(view.open(revision.source))
        for ref in frontier.refs:
            history = view.lineage(frontier, ref.revision)
            domains.validate(tuple(entry for _, entry in history))
    # A complete backup cannot silently retain an unexplained or unverified object.
    if set(view.observed) != set(objects):
        raise NativeError("incomplete")
    if monotonic() - started > budget.seconds:
        raise NativeError("incomplete")
    return view


def archive(service: Service, access: Access, recipient: EnvelopeService | None = None) -> tuple[Context, bytes]:
    """
    Produce a signed encrypted full-history export with the current keys or an explicitly configured recipient.

    Args:
        service (Service): Authenticated native runtime.
        access (Access): Whole-identity export grant.
        recipient (EnvelopeService | None): Explicit independently pinned sharing keys; None uses current operational keys.

    Returns:
        tuple[Context, bytes]: Expected opaque context and signed encrypted export, verified before release.
    """
    started = service.monotonic()
    registration, _ = service.snapshot(access, "export", "*")
    retained = Archive(access.scope, service.store.history(access.scope))
    if retained.head != registration.head:
        raise NativeError("conflict")
    verify(service, access, retained)
    keys = recipient or service.keys(access)
    payload = retained.encode(keys.limits)
    context = Context(access.scope.tenant, access.scope.identity, str(uuid4()), BACKUP)
    sealed = keys.seal(context, payload)
    keys.verify(context, sealed)
    service.release(access, "export", "*", registration, started)
    return context, sealed


def restore(
    service: Service, access: Access, context: Context, sealed: bytes, target: Store, recipient: EnvelopeService | None = None
) -> Head:
    """
    Restore-test a signed encrypted backup into an empty or identical-prefix inactive destination without changing authority.

    Args:
        service (Service): Current trusted runtime; production cutover is a separate fenced operation.
        access (Access): Current export or migration grant.
        context (Context): Independently expected source context, not inferred from an untrusted envelope.
        sealed (bytes): Complete signed encrypted export.
        target (Store): Explicit inactive destination, never selected automatically by configuration.
        recipient (EnvelopeService | None): Explicit backup custody, or current operational custody.

    Returns:
        Head: Independently read-back restored frontier; registry authority is unchanged.
    """
    identifier(context.record)
    if context.tenant != access.scope.tenant or context.identity != access.scope.identity or context.kind != BACKUP:
        raise NativeError("denied")
    started = service.monotonic()
    service.protection()
    registration = service.authority.check(access, "import", "*", int(service.clock()))
    if service.authority.check(access, "export", "*", int(service.clock())) != registration:
        raise NativeError("conflict")
    if target is service.store:
        raise NativeError("denied")
    keys = recipient or service.keys(access)
    retained = Archive.decode(binary(keys.open(context, sealed)), keys.limits)
    verify(service, access, retained)
    existing = target.history(access.scope)
    if retained.batches[: len(existing)] != existing:
        raise NativeError("conflict")
    # An interrupted restore resumes only an exact prefix; it never overwrites divergence.
    for batch in retained.batches[len(existing) :]:
        target.commit(access.scope, batch)
    if target.history(access.scope) != retained.batches or target.head(access.scope) != retained.head:
        raise NativeError("incomplete")
    service.release(access, "import", "*", registration, started)
    service.release(access, "export", "*", registration, started)
    return retained.head
