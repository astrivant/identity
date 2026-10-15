"""
Rotate current native representations without rewriting retained semantic history or retiring historical recovery keys.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from attrs import evolve

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.context import Context, identifier
from witful.native.service import REVISION
from witful.native.storage import Object

if TYPE_CHECKING:
    from witful.native.authority import Access
    from witful.native.models import Pointer, Receipt
    from witful.native.service import Service

__all__ = ["rotate"]

ROTATION = 8


def rotate(service: Service, access: Access, operation: str, mode: Literal["rewrap", "reseal", "resign"]) -> Receipt:
    """
    Publish current representations under configured key generations and retain an encrypted original-to-new mapping.

    Args:
        service (Service): Current runtime configured with independently approved new key generations and historical trust pins.
        access (Access): Current whole-identity write and rotate admission.
        operation (str): Stable retry UUID bound to the mode and configured generations.
        mode (Literal["rewrap", "reseal", "resign"]): Explicit data-key rewrap, fresh data encryption or signature-only rotation.

    Returns:
        Receipt: Durable rotation preserving logical UUIDs, original journals, parent order and retained historical ciphertext.
    """
    identifier(operation)
    if mode not in {"rewrap", "reseal", "resign"}:
        raise NativeError("invalid")
    started = service.monotonic()
    service.protection()
    admitted = service.authority.check(access, "rotate", "*", int(service.clock()))
    registration, frontier = service.snapshot(access, "write", "*")
    if admitted != registration or frontier.outbox:
        raise NativeError("conflict")
    keys = service.keys(access)
    request = hashlib.sha256(codec.encode(["witful-rotation-v1", mode, keys.wrapping, keys.signing])).hexdigest()
    previous = service.previous(access, operation, request)
    if previous is not None:
        service.release(access, "rotate", "*", registration, started)
        return previous
    objects: list[Object] = []
    mappings: dict[str, Pointer] = {}
    originals: dict[str, Pointer] = {}
    total = 0

    def transform(pointer: Pointer) -> Pointer:
        """
        Rotate one immutable payload once even when several revisions reference it.

        Args:
            pointer (Pointer): Authenticated current representation.

        Returns:
            Pointer: New independently verified representation under the same immutable context.
        """
        nonlocal total
        if pointer.object in mappings:
            if originals[pointer.object] != pointer:
                raise NativeError("invalid")
            return mappings[pointer.object]
        if service.monotonic() - started > service.budget.seconds:
            raise NativeError("incomplete")
        original = service.store.get(access.scope, (pointer.object,))[0]
        if original.digest.hex() != pointer.digest:
            raise NativeError("invalid")
        total += len(original.payload)
        if total > service.budget.bytes:
            raise NativeError("incomplete")
        context = Context(access.scope.tenant, access.scope.identity, pointer.record, pointer.kind)
        action = {"rewrap": keys.rewrap, "reseal": keys.reseal, "resign": keys.resign}[mode]
        result = Object(str(uuid4()), action(context, original.payload))
        keys.verify(context, result.payload)
        updated = evolve(pointer, object=result.id, digest=result.digest.hex())
        mappings[pointer.object] = updated
        originals[pointer.object] = pointer
        objects.append(result)
        return updated

    revisions: list[Pointer] = []
    for pointer in frontier.revisions:
        revision = service.revision(access, frontier, pointer.record)
        updated_revision = evolve(
            revision, payload=transform(revision.payload), source=transform(revision.source) if revision.source else None
        )
        # Metadata must be resealed because its representation pointers changed; logical history remains unchanged.
        updated, sealed = service.seal(access, revision.id, REVISION, as_data(updated_revision))
        revisions.append(updated)
        mappings[pointer.object] = updated
        originals[pointer.object] = pointer
        objects.append(sealed)
    archives = tuple(transform(pointer) for pointer in frontier.archives)
    manifest, sealed = service.seal(
        access,
        str(uuid4()),
        ROTATION,
        {
            "version": 1,
            "operation": operation,
            "mode": mode,
            "wrapping": keys.wrapping,
            "signing": keys.signing,
            "mappings": [[as_data(originals[original]), as_data(updated)] for original, updated in sorted(mappings.items())],
            "history": "retained-originals-require-historical-keys",
            "recorded": int(service.clock()),
        },
    )
    objects.append(sealed)
    updated_frontier = evolve(frontier, revisions=tuple(revisions), archives=(*archives, manifest))
    service.release(access, "rotate", "*", registration, started)
    return service.commit(access, operation, request, registration, updated_frontier, tuple(objects), started, permission="rotate")
