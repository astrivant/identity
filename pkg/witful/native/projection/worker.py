"""
Persist conservative delivery attempts and independent verification results without retrying with new Git bytes.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID, uuid5

from attrs import evolve

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.client import Client, ClientSettings
from witful.native.projection.models import PREPARED, RESULT, Prepared, Result
from witful.native.projection.preparation import authorize, first, load, prepare
from witful.native.wire import integer, mapping

if TYPE_CHECKING:
    from witful.native.authority import Access
    from witful.native.models import Pointer
    from witful.native.projection.models import Target
    from witful.native.service import Service

State = Literal["projection_pending", "unknown", "blocked", "diverged"]


class Transport(Protocol):
    """
    Keep the caller-owned mutually authenticated network boundary replaceable for deterministic failure tests.
    """

    def __call__(self, target: Target, access: Access, arguments: dict[str, object], byte_limit: int) -> object:
        """
        Invoke the configured isolated gateway without selecting arbitrary remotes or performing an implicit retry.

        Args:
            target (Target): Retained approved gateway transport settings.
            access (Access): Current native scope/epoch/policy for the gateway's independent grant.
            arguments (dict[str, object]): Exact prepared request bytes and opaque operation identifiers.
            byte_limit (int): Explicit complete request/response bound.

        Returns:
            object: Untrusted decoded response requiring exact candidate verification.
        """
        ...


def transport(target: Target, access: Access, arguments: dict[str, object], byte_limit: int) -> object:
    """
    Reuse the native mutual-TLS client with the explicitly separate gateway grant and mounted client certificate.

    Args:
        target (Target): Approved immutable transport selection.
        access (Access): Current source scope, epoch and policy.
        arguments (dict[str, object]): Exact opaque publication request.
        byte_limit (int): Complete payload bound.

    Returns:
        object: One gateway response without hidden retries.
    """
    settings = ClientSettings(
        target.url,
        target.ca,
        target.certificate,
        target.key,
        access.scope.tenant,
        access.scope.identity,
        target.grant,
        target.task,
        access.epoch,
        access.policy,
        max_bytes=byte_limit,
    )
    return Client(settings).invoke("project-deliver", arguments)


def retain(
    service: Service, access: Access, pointer: Pointer, prepared: Prepared, state: State, verified: bool = False
) -> tuple[Pointer, Prepared]:
    """
    Atomically retain exact retry progress or remove work only after independent successful remote verification.

    Args:
        service (Service): Current source runtime.
        access (Access): Authenticated worker with write/project/export authority.
        pointer (Pointer): Expected current outbox representation, guarding concurrent updates.
        prepared (Prepared): Complete unchanged Git candidate plus observed attempt state.
        state (State): Conservative pending or failed delivery state.
        verified (bool): Whether this call follows exact independently verified remote content.

    Returns:
        tuple[Pointer, Prepared]: New encrypted attempt pointer, or retained source candidate on completion.
    """
    started = service.monotonic()
    registration, frontier = service.snapshot(access, "project", "*")
    current, original = first(service, access, frontier, prepared.intent.target.id)
    if current != pointer or original != prepared.intent:
        raise NativeError("conflict")
    authorize(service, access, original, registration)
    if verified:
        result = Result(pointer, prepared.oid, int(service.clock()))
        updated, sealed = service.seal(access, str(uuid5(UUID(pointer.record), "verified")), RESULT, as_data(result))
        candidate = evolve(
            frontier, archives=(*frontier.archives, updated), outbox=tuple(item for item in frontier.outbox if item != pointer)
        )
        label = "verified"
        data: object = as_data(result)
    else:
        prepared = evolve(prepared, state=state)
        updated, sealed = service.seal(access, pointer.record, PREPARED, as_data(prepared))
        candidate = evolve(frontier, outbox=tuple(updated if item == pointer else item for item in frontier.outbox))
        label = f"attempt:{prepared.attempts}:{state}"
        data = as_data(prepared)
    operation = str(uuid5(UUID(pointer.record), label))
    request = hashlib.sha256(b"witful-projection-progress-v1\0" + codec.encode(data, service.keys(access).limits)).hexdigest()
    service.commit(
        access,
        operation,
        request,
        registration,
        candidate,
        (sealed,),
        started,
        permission="project",
        project=False,
        requirements=("export",),
    )
    return (pointer if verified else updated), prepared


def deliver(service: Service, access: Access, target: str, author: str, email: str, send: Transport = transport) -> dict[str, object]:
    """
    Prepare or resume the oldest candidate and make one bounded attempt with persisted backoff and exact immutable request bytes.

    Args:
        service (Service): Current native controller.
        access (Access): Current authorized worker.
        target (str): Opaque configured destination.
        author (str): Approved honest exporter name for newly prepared work.
        email (str): Approved exporter contact for newly prepared work.
        send (Transport): Explicit single-call transport boundary.

    Returns:
        dict[str, object]: Independent delivery state; uncertainty never satisfies a remote-required gate.
    """
    pointer, prepared = prepare(service, access, target, author, email)
    now = int(service.clock())
    if now < prepared.next_attempt:
        return {"state": prepared.state, "operation": prepared.intent.operation, "target": target, "oid": prepared.oid}
    bundle, _, envelope = load(service, access, prepared)
    # Persist uncertainty before contacting the remote. A crash cannot leave an attempted effect labeled unattempted.
    policy = service.projection
    exponent = min(prepared.attempts, policy.retry_max_seconds.bit_length())
    delay = min(policy.retry_max_seconds, policy.retry_seconds * (2**exponent))
    attempted = evolve(prepared, attempts=prepared.attempts + 1, next_attempt=now + delay)
    pointer, attempted = retain(service, access, pointer, attempted, "unknown")
    arguments: dict[str, object] = {
        "target": target,
        "operation": prepared.intent.operation,
        "permit": envelope,
        "bundle": bundle.encode(service.keys(access).limits),
    }
    try:
        raw = send(prepared.intent.target, access, arguments, service.budget.bytes)
        response = mapping(raw, {"state", "operation", "target", "generation", "oid"})
        integer(response["generation"])
        expected = {
            "state": "remote_verified",
            "operation": prepared.intent.operation,
            "target": target,
            "generation": prepared.intent.generation,
            "oid": prepared.oid,
        }
        if response != expected:
            raise NativeError("invalid")
    except NativeError as error:
        state: State = (
            "diverged" if error.code == "diverged" else "blocked" if error.code in {"invalid", "denied", "conflict"} else "unknown"
        )
        if state != "unknown":
            retain(service, access, pointer, attempted, state)
        return {"state": state, "operation": prepared.intent.operation, "target": target, "oid": prepared.oid}
    retain(service, access, pointer, attempted, "unknown", verified=True)
    return expected
