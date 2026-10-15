"""
Attach encrypted durable outbox intent to accepted native writes and enforce explicit backlog pressure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from attrs import evolve

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native.models import parse
from witful.native.projection.models import INTENT, PREPARED, Intent, Prepared

if TYPE_CHECKING:
    from witful.native.authority import Access, Registration
    from witful.native.models import Frontier, Pointer
    from witful.native.service import Service
    from witful.native.storage import Object


def read(service: Service, access: Access, pointer: Pointer) -> Intent:
    """
    Resolve accepted intent through its authenticated current outbox pointer.

    Args:
        service (Service): Admitted native source.
        access (Access): Current authorized source bindings.
        pointer (Pointer): Trusted frontier outbox pointer.

    Returns:
        Intent: Original accepted work, with prepared retry state retained separately.
    """
    if pointer.kind == INTENT:
        return parse(service.open(access, pointer), Intent)
    if pointer.kind == PREPARED:
        return parse(service.open(access, pointer), Prepared).intent
    raise NativeError("unsupported")


def enqueue(
    service: Service,
    access: Access,
    operation: str,
    registration: Registration,
    frontier: Frontier,
    objects: tuple[Object, ...],
) -> tuple[Frontier, tuple[Object, ...]]:
    """
    Seal one stable intent per configured target in the same candidate as its accepted records and receipt.

    Args:
        service (Service): Configured native runtime and current custody.
        access (Access): Admitted writer, separately requiring current whole-identity project and export permissions.
        operation (str): Stable source write operation UUID.
        registration (Registration): Expected pre-write acknowledged source.
        frontier (Frontier): Complete proposed logical refs and retained pending work.
        objects (tuple[Object, ...]): Already sealed record candidates.

    Returns:
        tuple[Frontier, tuple[Object, ...]]: Complete augmented candidate, or a refusal before any durable effect.
    """
    policy = service.projection
    targets = policy.select(access.scope.tenant, access.scope.identity)
    if not targets:
        return frontier, objects
    now = int(service.clock())
    for permission in ("project", "export"):
        if service.authority.check(access, permission, "*", now) != registration:
            raise NativeError("conflict")
    if len(frontier.outbox) + len(targets) > policy.max_entries:
        raise NativeError("unavailable")
    size = 0
    for pointer in frontier.outbox:
        intent = read(service, access, pointer)
        if now - intent.recorded > policy.max_lag_seconds:
            raise NativeError("unavailable")
        pointers: tuple[Pointer, ...] = (pointer,)
        if pointer.kind == PREPARED:
            prepared = parse(service.open(access, pointer), Prepared)
            pointers += (prepared.bundle, prepared.permit)
        size += sum(len(item.payload) for item in service.store.get(access.scope, tuple(value.object for value in pointers)))
    pending = list(frontier.outbox)
    additions = list(objects)
    for target in targets:
        intent = Intent(
            operation, service.authority.backend, access, target, registration.head.generation + 1, now, policy.mode == "required"
        )
        record = str(uuid5(UUID(operation), target.id))
        pointer, sealed = service.seal(access, record, INTENT, as_data(intent))
        size += len(sealed.payload)
        if size > policy.max_bytes:
            raise NativeError("unavailable")
        pending.append(pointer)
        additions.append(sealed)
    return evolve(frontier, outbox=tuple(pending)), tuple(additions)
