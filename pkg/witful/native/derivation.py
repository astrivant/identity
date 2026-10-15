"""
Publish reviewed independently scoped forks and splits through one recoverable authority transaction.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from attrs import evolve, field, frozen

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec, domains
from witful.native.backup import Archive, verify
from witful.native.context import Context, identifier
from witful.native.derivation_models import ChildEvidence, Decision, Output
from witful.native.kinds import DERIVATION, DOMAIN, FRONTIER, RECEIPT, REVISION
from witful.native.models import Adoption, Frontier, Pointer, Receipt, Ref, Revision, parse
from witful.native.postgres import sql
from witful.native.storage import Head
from witful.native.wire import binary, decode_batch, encode_batch, mapping, sequence, text

if TYPE_CHECKING:
    from witful.native.authority import Access, Authority, Registration
    from witful.native.reconciliation import Selection
    from witful.native.service import Service
    from witful.native.storage import Batch, Object, Scope

__all__ = ["Child", "derive"]

PREPARATION = 13


@frozen
class Child:
    """
    Select an independently provisioned recipient scope and an explicit reviewed adoption, without inheriting parent access.

    Attributes:
        service (Service): Operator-selected existing destination storage and custody.
        access (Access): Independently granted recipient-scope derive, import and write permission for this authenticated actor.
        ref (str): Newly created child branch name.
        selections (tuple[Selection, ...]): Explicit source mappings and authored child records, valid as a new domain history.
    """

    service: Service = field(repr=False)
    access: Access
    ref: str
    selections: tuple[Selection, ...] = field(repr=False)


def members(
    source: Service,
    access: Access,
    children: tuple[Child, ...],
) -> tuple[tuple[Authority, Access, tuple[str, ...]], ...]:
    """
    Require source disclosure/review and separate destination import permissions under the same actual authenticated subject.

    Args:
        source (Service): Current parent service.
        access (Access): Authenticated parent request.
        children (tuple[Child, ...]): Explicit independently provisioned targets.

    Returns:
        tuple[tuple[Authority, Access, tuple[str, ...]], ...]: Ordered transaction bindings; scopes are locked canonically by Authority.
    """
    if not children or len(children) > source.budget.refs:
        raise NativeError("incomplete")
    source.protection()
    for child in children:
        child.service.protection()
        if child.access.subject != access.subject or not child.ref or not child.selections:
            raise NativeError("denied")
    return (
        (source.authority, access, ("review", "export", "write")),
        *((child.service.authority, child.access, ("import", "write")) for child in children),
    )


def binding(access: Access, expected: str, children: tuple[Child, ...], reason: str, limits: codec.Limits) -> str:
    """
    Bind retries to the complete reviewed disclosure and destination policy expectations, never only an operation name.

    Args:
        access (Access): Source scope and authenticated approval bindings.
        expected (str): Exact reviewed source frontier UUID.
        children (tuple[Child, ...]): Ordered independently scoped output definitions.
        reason (str): Explicit reviewer rationale.
        limits (codec.Limits): Aggregate semantic input bound.

    Returns:
        str: Protected semantic digest retained only inside encrypted receipts and preparation.
    """
    return hashlib.sha256(
        b"witful-native-derivation-v1\0"
        + codec.encode(
            {
                "access": as_data(access),
                "expected": expected,
                "reason": reason,
                "children": [
                    {
                        "backend": child.service.authority.backend,
                        "access": as_data(child.access),
                        "ref": child.ref,
                        "selections": [[list(selection.sources), domains.encode(selection.entry)] for selection in child.selections],
                    }
                    for child in children
                ],
            },
            limits,
        )
    ).hexdigest()


def child_candidate(
    child: Child,
    operation: str,
    request: str,
    registration: Registration,
    source: Pointer,
    source_scope: Scope,
    available: set[str],
    reason: str,
    recorded: str,
) -> tuple[Batch, Output]:
    """
    Seal only explicit reviewed child records and selected provenance; never copy ancestors or whole import-source files.

    Args:
        child (Child): Independently authorized empty recipient.
        operation (str): Stable derivation UUID.
        request (str): Complete review digest.
        registration (Registration): Independently observed empty recipient frontier.
        source (Pointer): Exact reviewed parent frontier.
        source_scope (Scope): Opaque source-scope metadata explicitly disclosed with selected provenance.
        available (set[str]): Parent revision IDs available at that frontier.
        reason (str): Reviewed disclosure rationale.
        recorded (str): Actual adoption time, not a fabricated original authoring time.

    Returns:
        tuple[Batch, Output]: Exact sealed child transaction and parent-owned complete child mapping.
    """
    if registration.head != Head() or child.service.store.history(child.access.scope):
        raise NativeError("conflict")
    if len(child.selections) > child.service.budget.revisions:
        raise NativeError("incomplete")
    for selection in child.selections:
        if not selection.sources or len(set(selection.sources)) != len(selection.sources) or not set(selection.sources) <= available:
            raise NativeError("invalid")
    domains.validate(tuple(selection.entry for selection in child.selections))
    pointers: list[Pointer] = []
    objects: list[Object] = []
    adopted: list[Adoption] = []
    parents: tuple[str, ...] = ()
    for selection in child.selections:
        record = str(uuid4())
        payload, sealed = child.service.seal(child.access, str(uuid4()), DOMAIN, domains.encode(selection.entry))
        objects.append(sealed)
        # The child has new honest ancestry. Selected parent IDs are evidence, never traversable permission grants.
        revision = Revision(record, selection.entry.domain, payload, parents, operation, recorded)
        pointer, sealed = child.service.seal(child.access, record, REVISION, as_data(revision))
        pointers.append(pointer)
        objects.append(sealed)
        adopted.append(Adoption(selection.sources, record))
        parents = (record,)
    evidence = ChildEvidence(source_scope, source, tuple(adopted), child.access.subject, reason, recorded)
    archive, sealed = child.service.seal(child.access, str(uuid4()), DERIVATION, as_data(evidence))
    objects.append(sealed)
    frontier = Frontier(refs=(Ref(child.ref, parents[0], 1),), revisions=tuple(pointers), archives=(archive,))
    batch, _ = child.service.candidate(child.access, operation, request, registration, frontier, tuple(objects))
    return batch, Output(
        child.access.scope,
        child.service.authority.backend,
        Pointer(batch.root.id, batch.root.id, FRONTIER, batch.root.digest.hex()),
        child.ref,
        tuple(adopted),
    )


def prepare(
    source: Service,
    access: Access,
    operation: str,
    request: str,
    expected: str,
    children: tuple[Child, ...],
    reason: str,
    registrations: tuple[Registration, ...],
) -> tuple[bytes, tuple[Batch, ...]]:
    """
    Build and authenticate every output before freezing or mutating any durable scope.

    Args:
        source (Service): Current parent source and signing custody.
        access (Access): Source disclosure request.
        operation (str): Stable group operation UUID.
        request (str): Complete semantic input digest.
        expected (str): Exact reviewed parent frontier.
        children (tuple[Child, ...]): Explicit reviewed child outputs.
        reason (str): Nonempty review rationale.
        registrations (tuple[Registration, ...]): Source followed by child snapshots observed atomically.

    Returns:
        tuple[bytes, tuple[Batch, ...]]: Encrypted durable recovery packet and exact source/child transactions.
    """
    registration, frontier = source.snapshot(access, "derive", "*")
    if registration != registrations[0] or registration.head.root != expected:
        raise NativeError("conflict")
    root = Pointer(expected, expected, FRONTIER, registration.head.digest.hex())
    available = {pointer.record for pointer in frontier.revisions}
    if sum(len(child.selections) for child in children) > source.budget.revisions:
        raise NativeError("incomplete")
    recorded = datetime.fromtimestamp(source.clock(), UTC).isoformat()
    batches: list[Batch] = []
    outputs: list[Output] = []
    for child, observed in zip(children, registrations[1:], strict=True):
        batch, output = child_candidate(
            child,
            operation,
            request,
            observed,
            root,
            access.scope,
            available,
            reason,
            recorded,
        )
        batches.append(batch)
        outputs.append(output)
    disclosed = {record for child in children for selection in child.selections for record in selection.sources}
    evidence = Decision(
        "fork" if len(children) == 1 else "split",
        root,
        tuple(outputs),
        tuple(sorted(available - disclosed)),
        reason,
        access.subject,
        recorded,
    )
    decision, sealed = source.seal(access, str(uuid4()), DERIVATION, as_data(evidence))
    parent, _ = source.candidate(
        access,
        operation,
        request,
        registration,
        evolve(frontier, archives=(*frontier.archives, decision)),
        (sealed,),
    )
    result = (parent, *batches)
    context = Context(access.scope.tenant, access.scope.identity, operation, PREPARATION)
    prepared = source.keys(access).seal(
        context,
        {
            "request": request,
            "batches": [encode_batch(batch, source.authority.limits) for batch in result],
        },
    )
    packet = codec.encode({"derivation": context.data(), "sealed": prepared}, source.authority.limits)
    return packet, result


def candidates(source: Service, access: Access, operation: str, request: str, packet: bytes) -> tuple[Batch, ...]:
    """
    Recover prepared ciphertext without new randomness, timestamps or recipient choices.

    Args:
        source (Service): Current parent custody and independent signer pins.
        access (Access): Current source request.
        operation (str): Expected original operation UUID.
        request (str): Complete unchanged semantic request.
        packet (bytes): Trusted control-plane preparation, still independently authenticated before use.

    Returns:
        tuple[Batch, ...]: Exact original source and child transactions.
    """
    outer = mapping(codec.decode(packet, source.authority.limits), {"derivation", "sealed"})
    context = Context(access.scope.tenant, access.scope.identity, operation, PREPARATION)
    if parse(outer["derivation"], Context) != context:
        raise NativeError("conflict")
    body = mapping(source.keys(access).open(context, binary(outer["sealed"])), {"request", "batches"})
    if text(body["request"]) != request:
        raise NativeError("conflict")
    return tuple(decode_batch(binary(item), source.authority.limits) for item in sequence(body["batches"]))


def verify_candidate(service: Service, access: Access, batch: Batch) -> None:
    """
    Validate the complete resulting history even when a prior attempt committed this exact transaction before losing its receipt.

    Args:
        service (Service): Explicit scope's data and custody boundary.
        access (Access): Current independently authorized scope.
        batch (Batch): Durable exact candidate.

    Returns:
        None: The existing history is exactly the expected prefix or exact result, and all resulting bytes verify.
    """
    history = service.store.history(access.scope)
    if history and history[-1] == batch:
        history = history[:-1]
    archive = Archive(access.scope, history)
    if archive.head != batch.expected:
        raise NativeError("conflict")
    verify(service, access, Archive(access.scope, (*history, batch)))


def derive(
    source: Service,
    access: Access,
    operation: str,
    expected: str,
    children: tuple[Child, ...],
    reason: str,
) -> Receipt:
    """
    Resume or publish an independently scoped reviewed fork/split with atomic visibility and exact retained retry bytes.

    Args:
        source (Service): Parent authoritative service.
        access (Access): Authenticated source disclosure and review grant.
        operation (str): Stable derivation operation UUID, reused unchanged after interruption.
        expected (str): Exact source frontier UUID selected by the reviewer.
        children (tuple[Child, ...]): Ordered configured recipient scopes and explicit authored selections.
        reason (str): Explicit disclosure rationale, retained encrypted.

    Returns:
        Receipt: Durable parent receipt only after every output's independent readback and one atomic authority publication.
    """
    identifier(operation)
    identifier(expected)
    if not reason.strip():
        raise NativeError("invalid")
    started = source.monotonic()
    bindings = members(source, access, children)
    request = binding(access, expected, children, reason, source.authority.limits)
    with source.authority.group(bindings, int(source.clock())) as (_, registrations):
        pass
    targets = ((source, access), *((child.service, child.access) for child in children))
    packet = registrations[0].transition
    if packet is None:
        if any(registration.transition is not None for registration in registrations):
            raise NativeError("unknown")
        if any(
            service.store.head(target_access.scope) != registration.head
            for (service, target_access), registration in zip(targets, registrations, strict=True)
        ):
            raise NativeError("conflict")
        previous = source.previous(access, operation, request)
        if previous is not None:
            members(source, access, children)
            with source.authority.group(bindings, int(source.clock())) as (_, current):
                if current != registrations:
                    raise NativeError("conflict")
            return previous
        packet, batches = prepare(source, access, operation, request, expected, children, reason, registrations)
    else:
        if any(registration.transition != packet for registration in registrations):
            raise NativeError("conflict")
        batches = candidates(source, access, operation, request, packet)
    if len(batches) != len(targets):
        raise NativeError("invalid")
    for (service, target_access), batch, registration in zip(targets, batches, registrations, strict=True):
        if batch.operation != operation or batch.expected != registration.head:
            raise NativeError("conflict")
        verify_candidate(service, target_access, batch)
    if source.monotonic() - started > source.budget.seconds:
        raise NativeError("incomplete")
    # Freeze all scopes together. No child becomes readable because one data copy happens to finish first.
    with source.authority.group(bindings, int(source.clock())) as (connection, current):
        if current != registrations:
            raise NativeError("conflict")
        for _, target_access in targets:
            connection.execute(sql("authority-transition"), (packet, target_access.scope.tenant, target_access.scope.identity))
    frozen = tuple(evolve(registration, transition=packet) for registration in registrations)
    # Custody and storage work occurs outside control-plane locks. The durable group fence blocks normal writers and readers.
    for (service, target_access), batch in zip(targets, batches, strict=True):
        members(source, access, children)
        with source.authority.group(bindings, int(source.clock())) as (_, current):
            if current != frozen:
                raise NativeError("conflict")
        if source.monotonic() - started > source.budget.seconds:
            raise NativeError("incomplete")
        service.store.commit(target_access.scope, batch)
        head, receipt = service.store.resolve(target_access.scope, operation)
        if head != batch.target or receipt != batch.receipt:
            raise NativeError("unknown")
    members(source, access, children)
    if source.monotonic() - started > source.budget.seconds:
        raise NativeError("incomplete")
    with source.authority.group(bindings, int(source.clock())) as (connection, current):
        if current != frozen:
            raise NativeError("conflict")
        for (_, target_access), batch in zip(targets, batches, strict=True):
            head = batch.target
            connection.execute(
                sql("authority-ack"), (head.generation, head.root, head.digest, target_access.scope.tenant, target_access.scope.identity)
            )
            connection.execute(sql("authority-transition"), (None, target_access.scope.tenant, target_access.scope.identity))
    result = parse(
        source.keys(access).open(Context(access.scope.tenant, access.scope.identity, operation, RECEIPT), batches[0].receipt.payload),
        Receipt,
    )
    # A revocation after publication may deny this response; retry still finds the durable original operation receipt.
    members(source, access, children)
    with source.authority.group(bindings, int(source.clock())):
        pass
    return result
