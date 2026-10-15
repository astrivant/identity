"""
Report retained delivery evidence and enforce remote-required completion independently of local durable receipts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from witful.exceptions import NativeError
from witful.native.context import Context, identifier
from witful.native.kinds import RECEIPT
from witful.native.models import Frontier, Receipt, parse
from witful.native.projection.intents import read
from witful.native.projection.models import PREPARED, RESULT, Prepared, Result

if TYPE_CHECKING:
    from witful.native.authority import Access
    from witful.native.models import Pointer
    from witful.native.service import Service


def status(service: Service, access: Access) -> dict[str, object]:
    """
    Inspect only authorized encrypted queue metadata and retained verified results, without probing or contacting a remote.

    Args:
        service (Service): Current native source.
        access (Access): Current whole-identity projection grant.

    Returns:
        dict[str, object]: Exact backlog, retry state and last verified frontier per opaque destination.
    """
    started = service.monotonic()
    registration, frontier = service.snapshot(access, "project", "*")
    pending: list[dict[str, object]] = []
    size = 0
    oldest = 0
    now = int(service.clock())
    for pointer in frontier.outbox:
        intent = read(service, access, pointer)
        prepared = parse(service.open(access, pointer), Prepared) if pointer.kind == PREPARED else None
        pointers: tuple[Pointer, ...] = (pointer,)
        if prepared is not None:
            pointers += (prepared.bundle, prepared.permit)
        size += sum(len(item.payload) for item in service.store.get(access.scope, tuple(item.object for item in pointers)))
        age = max(0, now - intent.recorded)
        oldest = max(oldest, age)
        pending.append(
            {
                "operation": intent.operation,
                "target": intent.target.id,
                "generation": intent.generation,
                "required": intent.required,
                "age_seconds": age,
                "state": prepared.state if prepared else "projection_pending",
                "attempts": prepared.attempts if prepared else 0,
                "next_attempt": prepared.next_attempt if prepared else 0,
            }
        )
    verified: dict[str, object] = {}
    for pointer in frontier.archives:
        if pointer.kind == RESULT:
            result = parse(service.open(access, pointer), Result)
            prepared = parse(service.open(access, result.prepared), Prepared)
            if result.oid != prepared.oid:
                raise NativeError("invalid")
            verified[prepared.intent.target.id] = {
                "operation": prepared.intent.operation,
                "generation": prepared.intent.generation,
                "oid": result.oid,
                "recorded": result.recorded,
            }
    service.release(access, "project", "*", registration, started)
    policy = service.projection
    return {
        "queue_size": len(pending),
        "queue_bytes": size,
        "oldest_seconds": oldest,
        "pending": pending,
        "verified": verified,
        "policy": {
            "mode": policy.mode,
            "attempts": policy.attempts,
            "retry_seconds": policy.retry_seconds,
            "retry_max_seconds": policy.retry_max_seconds,
            "targets": [item.id for item in policy.select(access.scope.tenant, access.scope.identity)],
        },
    }


def completion(service: Service, access: Access, operation: str) -> dict[str, object]:
    """
    Require every originally accepted required destination to have independent verification before reporting workload completion.

    Args:
        service (Service): Current source runtime.
        access (Access): Current authorized projection inspector.
        operation (str): Original stable native operation UUID.

    Returns:
        dict[str, object]: Explicit local durability and independent complete flag, with pending/verified destination counts.
    """
    started = service.monotonic()
    registration, frontier = service.snapshot(access, "project", "*")
    identifier(operation)
    stored = service.store.receipt(access.scope, operation)
    if stored is None:
        raise NativeError("incomplete")
    receipt = parse(
        service.keys(access).open(Context(access.scope.tenant, access.scope.identity, operation, RECEIPT), stored.payload), Receipt
    )
    if receipt.operation != operation:
        raise NativeError("invalid")
    accepted = parse(service.open(access, receipt.root), Frontier)
    expected = {
        intent.target.id
        for pointer in accepted.outbox
        if (intent := read(service, access, pointer)).operation == operation and intent.required
    }
    if receipt.remote_required != bool(expected):
        raise NativeError("invalid")
    outstanding = [read(service, access, pointer) for pointer in frontier.outbox]
    pending = sum(item.operation == operation and item.required for item in outstanding)
    verified: set[str] = set()
    for pointer in frontier.archives:
        if pointer.kind == RESULT:
            result = parse(service.open(access, pointer), Result)
            prepared = parse(service.open(access, result.prepared), Prepared)
            if result.oid != prepared.oid:
                raise NativeError("invalid")
            if prepared.intent.operation == operation and prepared.intent.required:
                if prepared.intent.target.id in verified:
                    raise NativeError("invalid")
                verified.add(prepared.intent.target.id)
    # Required work cannot disappear merely because configuration was disabled or a queue entry was lost.
    complete = not receipt.remote_required or (pending == 0 and verified == expected)
    service.release(access, "project", "*", registration, started)
    return {
        "operation": operation,
        "durability": receipt.outcome,
        "remote_required": receipt.remote_required,
        "complete": complete,
        "pending": pending,
        "verified": len(verified),
    }
