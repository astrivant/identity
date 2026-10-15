"""
Persist exact encrypted Git candidates before remote I/O and retain independent verification receipts afterward.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from attrs import evolve

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.backup import BACKUP, Archive, inspect
from witful.native.context import Context, identifier
from witful.native.models import parse
from witful.native.projection.bundle import Bundle
from witful.native.projection.bundle import prepare as prepare_bundle
from witful.native.projection.intents import read
from witful.native.projection.models import BUNDLE, INTENT, PERMIT, PREPARED, RESULT, Intent, Permit, Prepared, Result
from witful.native.projection.verification import candidate

if TYPE_CHECKING:
    from witful.native.authority import Access, Registration
    from witful.native.models import Frontier, Pointer
    from witful.native.service import Service


def authorize(service: Service, access: Access, intent: Intent, registration: Registration) -> None:
    """
    Check the worker and original writer against current independent policy without holding locks during custody or network work.

    Args:
        service (Service): Current source runtime.
        access (Access): Authenticated worker; transport delegation never invents the original writer's permissions.
        intent (Intent): Retained original authority bindings.
        registration (Registration): Expected current source snapshot.

    Returns:
        None: Both grants still permit this disclosure from the original backend and epoch.
    """
    if intent.backend != registration.backend or intent.generation > registration.head.generation or access.scope != intent.access.scope:
        raise NativeError("conflict")
    for actor in (access, intent.access):
        for action in ("project", "export"):
            if service.authority.check(actor, action, "*", int(service.clock())) != registration:
                raise NativeError("conflict")


def first(service: Service, access: Access, frontier: Frontier, target: str) -> tuple[Pointer, Intent]:
    """
    Select the oldest retained work for exactly one destination, preserving per-destination ordering.

    Args:
        service (Service): Current authenticated source reader.
        access (Access): Current worker bindings.
        frontier (Frontier): Independently acknowledged source frontier.
        target (str): Explicit opaque configured destination.

    Returns:
        tuple[Pointer, Intent]: First pending candidate; absence is a bounded incomplete result rather than invented success.
    """
    identifier(target)
    for pointer in frontier.outbox:
        intent = read(service, access, pointer)
        if intent.target.id == target:
            return pointer, intent
    raise NativeError("incomplete")


def parent(service: Service, access: Access, frontier: Frontier, intent: Intent) -> str | None:
    """
    Use the last independently verified publication as the next parent, preserving explicit create-if-absent for an empty destination.

    Args:
        service (Service): Admitted source runtime.
        access (Access): Current worker bindings.
        frontier (Frontier): Current authenticated metadata.
        intent (Intent): Selected pending destination.

    Returns:
        str | None: Exact expected remote head, never inferred from an unreviewed remote writer.
    """
    for pointer in reversed(frontier.archives):
        if pointer.kind == RESULT:
            result = parse(service.open(access, pointer), Result)
            prepared = parse(service.open(access, result.prepared), Prepared)
            if prepared.intent.target.id == intent.target.id:
                if prepared.oid != result.oid:
                    raise NativeError("invalid")
                return result.oid
    return intent.target.initial


def prepare(service: Service, access: Access, target: str, author: str, email: str) -> tuple[Pointer, Prepared]:
    """
    Verify the accepted history prefix, seal its export and retain exact Git/permit bytes before any delivery attempt.

    Args:
        service (Service): Current native controller with custody and bounded queue policy.
        access (Access): Current worker with explicit write, project and export permissions.
        target (str): Exact opaque destination UUID.
        author (str): Configured honest exporter name.
        email (str): Configured exporter contact.

    Returns:
        tuple[Pointer, Prepared]: Persisted candidate reused unchanged after a lost response or process restart.
    """
    started = service.monotonic()
    registration, frontier = service.snapshot(access, "project", "*")
    pointer, intent = first(service, access, frontier, target)
    authorize(service, access, intent, registration)
    if pointer.kind == PREPARED:
        prepared = parse(service.open(access, pointer), Prepared)
        service.release(access, "project", "*", registration, started)
        return pointer, prepared
    if pointer.kind != INTENT:
        raise NativeError("unsupported")

    # An intent selects an already committed prefix. Later bookkeeping cannot create a self-referential export.
    history = service.store.history(access.scope)
    retained = Archive(access.scope, tuple(batch for batch in history if batch.target.generation <= intent.generation))
    if retained.head.generation != intent.generation or retained.batches[-1].operation != intent.operation:
        raise NativeError("conflict")
    keys = service.keys(access)
    inspect(retained, keys, service.budget, service.monotonic)
    context = Context(access.scope.tenant, access.scope.identity, pointer.record, BACKUP)
    sealed = keys.seal(context, retained.encode(keys.limits))
    expected = parent(service, access, frontier, intent)
    recorded = int(service.clock())
    bundle = prepare_bundle(sealed, pointer.record, expected, author, email, recorded)
    raw = bundle.encode(keys.limits)
    blob, tree, commit = bundle.objects()
    permit = Permit(intent, context, expected, hashlib.sha256(raw).hexdigest(), commit[1], author, email, recorded)
    bundle_pointer, bundle_object = service.seal(access, str(uuid5(UUID(pointer.record), "bundle")), BUNDLE, raw)
    permit_pointer, permit_object = service.seal(access, str(uuid5(UUID(pointer.record), "permit")), PERMIT, as_data(permit))
    prepared = Prepared(intent, bundle_pointer, permit_pointer, expected, commit[1], tree[1], blob[1], author, email, recorded)
    updated, prepared_object = service.seal(access, pointer.record, PREPARED, as_data(prepared))

    # Refuse preparation before the authority/data commit if exact retry bytes cannot fit the configured queue budget.
    size = sum(len(item.payload) for item in (bundle_object, permit_object, prepared_object))
    for old in frontier.outbox:
        if old == pointer:
            continue
        pointers: tuple[Pointer, ...] = (old,)
        if old.kind == PREPARED:
            previous = parse(service.open(access, old), Prepared)
            pointers += (previous.bundle, previous.permit)
        size += sum(len(item.payload) for item in service.store.get(access.scope, tuple(value.object for value in pointers)))
    if size > service.projection.max_bytes:
        raise NativeError("unavailable")
    authorize(service, access, intent, registration)
    operation = str(uuid5(UUID(pointer.record), "prepare"))
    request = hashlib.sha256(b"witful-projection-prepare-v1\0" + codec.encode(as_data(intent), keys.limits)).hexdigest()
    candidate = evolve(frontier, outbox=tuple(updated if item == pointer else item for item in frontier.outbox))
    service.commit(
        access,
        operation,
        request,
        registration,
        candidate,
        (bundle_object, permit_object, prepared_object),
        started,
        permission="project",
        project=False,
        requirements=("export",),
    )
    return updated, prepared


def load(service: Service, access: Access, prepared: Prepared) -> tuple[Bundle, Permit, bytes]:
    """
    Authenticate and cross-check every retained candidate binding before handing ciphertext to a gateway.

    Args:
        service (Service): Admitted native source.
        access (Access): Current source worker.
        prepared (Prepared): Authenticated outbox metadata.

    Returns:
        tuple[Bundle, Permit, bytes]: Exact candidate, independently bound permit and original signed permit ciphertext.
    """
    bundle, permit = candidate(service.view(access), prepared)
    envelope = service.store.get(access.scope, (prepared.permit.object,))[0].payload
    return bundle, permit, envelope
