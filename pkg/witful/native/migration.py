"""
Migrate exact encrypted history through a durable write freeze and recoverable routing-epoch cutover.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from uuid import uuid4

from attrs import evolve, frozen

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.backup import Archive, archive, verify
from witful.native.context import Context, identifier
from witful.native.models import Frontier, Pointer, Receipt, parse
from witful.native.postgres import sql
from witful.native.service import FRONTIER, RECEIPT
from witful.native.storage import Object
from witful.native.wire import binary, decode_batch, encode_batch, mapping, text

if TYPE_CHECKING:
    from witful.native.authority import Access, Registration
    from witful.native.service import Service
    from witful.native.storage import Batch

__all__ = ["Transition", "abort", "migrate"]

MIGRATION = 7


@frozen
class Transition:
    """
    Retain the exact encrypted recovery source before freezing an identity's authority.

    Attributes:
        operation (str): Stable caller migration UUID.
        destination (str): Explicit inactive destination backend UUID.
        context (Context): Independently selected backup context.
        backup (bytes): Signed encrypted full-history backup, not plaintext migration records.
        prepared (bytes | None): Exact sealed cutover batch, durable before its first destination effect.
    """

    operation: str
    destination: str
    context: Context
    backup: bytes
    prepared: bytes | None = None

    def encode(self, limits: codec.Limits) -> bytes:
        """
        Encode the bounded control-plane transition without domain plaintext.

        Args:
            limits (codec.Limits): Configured authority preparation limit.

        Returns:
            bytes: Durable version-one transition representation.
        """
        return codec.encode(
            {
                "operation": self.operation,
                "destination": self.destination,
                "context": self.context.data(),
                "backup": self.backup,
                "prepared": self.prepared,
            },
            limits,
        )

    @classmethod
    def decode(cls, payload: bytes, limits: codec.Limits) -> Transition:
        """
        Validate a retained transition before resuming any destination effect.

        Args:
            payload (bytes): Trusted control-plane bytes, still structurally validated.
            limits (codec.Limits): Explicit bounded decoder settings.

        Returns:
            Transition: Closed recoverable migration state.
        """
        value = mapping(codec.decode(payload, limits), {"operation", "destination", "context", "backup", "prepared"})
        return cls(
            identifier(text(value["operation"])),
            identifier(text(value["destination"])),
            parse(value["context"], Context),
            binary(value["backup"]),
            None if value["prepared"] is None else binary(value["prepared"]),
        )


def binding(source: Service, destination: Service, access: Access) -> str:
    """
    Bind a migration to one unchanged scope, original epoch and explicitly distinct backend.

    Args:
        source (Service): Currently authoritative service.
        destination (Service): Explicit protected inactive service.
        access (Access): Original migration admission.

    Returns:
        str: Semantic retry digest retained only within the encrypted receipt.
    """
    source.protection()
    destination.protection()
    if source.authority.database_url != destination.authority.database_url or source.authority.backend == destination.authority.backend:
        raise NativeError("denied")
    return hashlib.sha256(
        codec.encode(["witful-migration-v1", source.authority.backend, destination.authority.backend, access.epoch])
    ).hexdigest()


def frozen_source(source: Service, access: Access, transition: Transition, registration: Registration) -> Archive:
    """
    Independently verify the complete retained backup and its equality to the frozen source.

    Args:
        source (Service): Original protected backend and key boundaries.
        access (Access): Current original-epoch migration grant.
        transition (Transition): Durable recovery source.
        registration (Registration): Frozen source acknowledgment.

    Returns:
        Archive: Complete authenticated original history, including any writes from an earlier migration.
    """
    keys = source.keys(access)
    retained = Archive.decode(binary(keys.open(transition.context, transition.backup)), keys.limits)
    verify(source, access, retained)
    if retained.head != registration.head or source.store.head(access.scope) != retained.head:
        raise NativeError("conflict")
    if source.store.history(access.scope) != retained.batches:
        raise NativeError("conflict")
    return retained


def cutover_candidate(source: Service, access: Access, transition: Transition, registration: Registration, request: str) -> Batch:
    """
    Seal the migration inventory and recovery source into retained native history before authority can change.

    Args:
        source (Service): Original key and data boundary.
        access (Access): Current original-epoch admission.
        transition (Transition): Exact recovery source and destination.
        registration (Registration): Frozen source frontier.
        request (str): Stable semantic migration binding.

    Returns:
        Batch: Exact candidate whose receipt records the newly admitted destination epoch.
    """
    head = registration.head
    frontier = (
        Frontier()
        if head.root is None
        else parse(source.open(access, Pointer(head.root, head.root, FRONTIER, head.digest.hex())), Frontier)
    )
    if frontier.outbox:
        raise NativeError("conflict")
    retained_backup = Object(str(uuid4()), transition.backup)
    backup_pointer = Pointer(transition.context.record, retained_backup.id, transition.context.kind, retained_backup.digest.hex())
    manifest, sealed = source.seal(
        access,
        str(uuid4()),
        MIGRATION,
        {
            "version": 1,
            "operation": transition.operation,
            "source": source.authority.backend,
            "destination": transition.destination,
            "previous_epoch": access.epoch,
            "next_epoch": access.epoch + 1,
            "source_head": {"generation": head.generation, "root": head.root, "digest": head.digest},
            "backup": as_data(backup_pointer),
            "scope": as_data(access.scope),
            "profile": "exact-native-history",
            "recorded": int(source.clock()),
        },
    )
    updated = evolve(frontier, archives=(*frontier.archives, backup_pointer, manifest))
    batch, _ = source.candidate(
        evolve(access, epoch=access.epoch + 1), transition.operation, request, registration, updated, (retained_backup, sealed)
    )
    return batch


def migrate(source: Service, destination: Service, access: Access, operation: str) -> Receipt:
    """
    Copy an exact retained prefix, fence the old writer and atomically select the verified destination's next epoch.

    Args:
        source (Service): Currently authoritative protected runtime, retained after cutover.
        destination (Service): Explicit inactive protected runtime with the same independent authority.
        access (Access): Current migration grant; the caller must explicitly adopt the returned next epoch.
        operation (str): Stable retry UUID; retry unchanged after an unknown acknowledgment.

    Returns:
        Receipt: Durable cutover receipt; reverse migration uses this same protocol and includes subsequent destination writes.
    """
    identifier(operation)
    request = binding(source, destination, access)
    started = source.monotonic()
    # A completed retry authenticates against the new authority; the stale source never regains write permission.
    next_access = evolve(access, epoch=access.epoch + 1)
    try:
        current = destination.authority.check(next_access, "migrate", "*", int(source.clock()))
    except NativeError as error:
        if error.code != "conflict":
            raise
    else:
        previous = destination.previous(next_access, operation, request)
        if previous is None:
            raise NativeError("conflict")
        destination.release(next_access, "migrate", "*", current, started)
        return previous
    with source.authority.guard(access, "migrate", "*", int(source.clock())) as (_, registration):
        if registration.pending is not None:
            raise NativeError("unknown")
    if registration.transition is None:
        context, sealed = archive(source, access)
        transition = Transition(operation, destination.authority.backend, context, sealed)
        payload = transition.encode(source.authority.limits)
        # Freeze after the backup was independently verified, only if no intervening write changed its frontier.
        with source.authority.guard(access, "migrate", "*", int(source.clock())) as (connection, current):
            if current != registration:
                raise NativeError("conflict")
            connection.execute(sql("authority-transition"), (payload, access.scope.tenant, access.scope.identity))
        registration = evolve(registration, transition=payload)
    else:
        transition = Transition.decode(registration.transition, source.authority.limits)
    if transition.operation != operation or transition.destination != destination.authority.backend:
        raise NativeError("conflict")
    retained = frozen_source(source, access, transition, registration)
    existing = destination.store.history(access.scope)
    prepared = decode_batch(transition.prepared, source.authority.limits) if transition.prepared is not None else None
    allowed = (*retained.batches, prepared) if prepared is not None else retained.batches
    if allowed[: len(existing)] != existing:
        raise NativeError("conflict")
    # The source is frozen. Each backfill transaction is serialized with cutover/abort in the independent control plane.
    for batch in retained.batches[len(existing) :]:
        with source.authority.guard(access, "migrate", "*", int(source.clock())) as (_, current):
            if current != registration:
                raise NativeError("conflict")
            destination.protection()
            destination.store.commit(access.scope, batch)
    if prepared is None:
        if destination.store.history(access.scope) != retained.batches:
            raise NativeError("incomplete")
        verify(destination, access, Archive(access.scope, destination.store.history(access.scope)))
        prepared = cutover_candidate(source, access, transition, registration, request)
        updated = evolve(transition, prepared=encode_batch(prepared, source.authority.limits))
        payload = updated.encode(source.authority.limits)
        with source.authority.guard(access, "migrate", "*", int(source.clock())) as (connection, current):
            if current != registration:
                raise NativeError("conflict")
            connection.execute(sql("authority-transition"), (payload, access.scope.tenant, access.scope.identity))
        registration = evolve(registration, transition=payload)
    source.protection()
    destination.protection()
    if source.monotonic() - started > source.budget.seconds:
        raise NativeError("incomplete")
    # The exact candidate was durable before the first effect. Lost acknowledgment resumes this same candidate.
    with source.authority.guard(access, "migrate", "*", int(source.clock())) as (connection, current):
        if current != registration or source.store.head(access.scope) != retained.head:
            raise NativeError("conflict")
        destination.store.resolve(access.scope, operation)
        target = destination.store.commit(access.scope, prepared)
        if target != prepared.target or destination.store.receipt(access.scope, operation) != prepared.receipt:
            raise NativeError("unknown")
        connection.execute(
            sql("authority-cutover"),
            (destination.authority.backend, target.generation, target.root, target.digest, access.scope.tenant, access.scope.identity),
        )
    # Recheck the destination's current policy before releasing the authenticated receipt.
    current = destination.authority.check(next_access, "migrate", "*", int(source.clock()))
    result = parse(
        source.keys(access).open(Context(access.scope.tenant, access.scope.identity, operation, RECEIPT), prepared.receipt.payload), Receipt
    )
    destination.release(next_access, "migrate", "*", current, started)
    return result


def abort(source: Service, access: Access, operation: str) -> None:
    """
    Unfreeze a migration only before any cutover candidate could have taken effect.

    Args:
        source (Service): Original authoritative runtime.
        access (Access): Current migration grant at the original epoch.
        operation (str): Exact migration to cancel; unrelated work is never cleared.

    Returns:
        None: Source authority resumes; inactive partial copies remain retained for explicit inventory and recovery.
    """
    source.protection()
    with source.authority.guard(access, "migrate", "*", int(source.clock())) as (connection, registration):
        if registration.transition is None:
            raise NativeError("conflict")
        transition = Transition.decode(registration.transition, source.authority.limits)
        if transition.operation != operation or transition.prepared is not None or source.store.head(access.scope) != registration.head:
            raise NativeError("conflict")
        connection.execute(sql("authority-transition"), (None, access.scope.tenant, access.scope.identity))
