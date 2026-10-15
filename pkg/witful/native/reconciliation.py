"""
Preserve competing native ancestry while requiring explicit, newly authored adoption into unchanged linear journal contracts.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from attrs import evolve, frozen

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec, domains
from witful.native.context import identifier
from witful.native.domains import Entry
from witful.native.models import Adoption, Reconciliation, Ref, Revision
from witful.native.service import DOMAIN, REVISION

if TYPE_CHECKING:
    from witful.native.authority import Access
    from witful.native.models import Receipt
    from witful.native.service import Service
    from witful.native.storage import Object


@frozen
class Selection:
    """
    Supply reviewed candidate evidence and an explicitly authored target-domain record.

    Attributes:
        sources (tuple[str, ...]): Candidate-only native revisions informing this adoption.
        entry (Entry): Newly authored record valid against the target's existing causal chain.
    """

    sources: tuple[str, ...]
    entry: Entry


def merge(
    service: Service,
    access: Access,
    operation: str,
    target: str,
    candidate: str,
    expected: str,
    reviewed: str,
    selections: tuple[Selection, ...],
    reason: str,
) -> Receipt:
    """
    Conditionally adopt reviewed records while retaining ordered ancestry and all rejected or deferred candidate evidence.

    Args:
        service (Service): Current authenticated native runtime.
        access (Access): Grant permitting both whole-identity write and review.
        operation (str): Stable reconciliation operation UUID.
        target (str): Existing mutable destination branch.
        candidate (str): Existing reviewed candidate branch.
        expected (str): Exact target logical head selected by the reviewer.
        reviewed (str): Exact candidate head selected by the reviewer.
        selections (tuple[Selection, ...]): Explicit source mappings and authored domain records; empty records a reviewed non-adoption.
        reason (str): Nonempty review rationale, retained encrypted.

    Returns:
        Receipt: Durable reconciliation; neither journal union nor a wall-clock winner is inferred.
    """
    identifier(operation)
    identifier(expected)
    identifier(reviewed)
    if not reason.strip() or expected == reviewed or target == candidate:
        raise NativeError("invalid")
    if any(item.entry.domain == "reconciliation" for item in selections):
        raise NativeError("denied")
    started = service.monotonic()
    request = hashlib.sha256(
        b"witful-native-review-v1\0"
        + codec.encode(
            [
                target,
                candidate,
                expected,
                reviewed,
                [[list(item.sources), domains.encode(item.entry)] for item in selections],
                reason,
            ],
            codec.Limits(bytes=service.budget.bytes),
        )
    ).hexdigest()
    service.protection()
    admitted_review = service.authority.check(access, "review", "*", int(service.clock()))
    registration, frontier = service.snapshot(access, "write", "*")
    if admitted_review != registration:
        raise NativeError("conflict")
    previous = service.previous(access, operation, request)
    if previous is not None:
        service.release(access, "review", "*", registration, started)
        return previous
    destination = next((item for item in frontier.refs if item.name == target), None)
    source = next((item for item in frontier.refs if item.name == candidate), None)
    if destination is None or source is None or destination.immutable or destination.revision != expected or source.revision != reviewed:
        raise NativeError("conflict")
    original = service.lineage(access, frontier, expected)
    proposed = service.lineage(access, frontier, reviewed)
    available = {revision.id for revision, _ in proposed} - {revision.id for revision, _ in original}
    accepted = {record for selection in selections for record in selection.sources}
    if not accepted <= available or any(
        not selection.sources or len(set(selection.sources)) != len(selection.sources) for selection in selections
    ):
        raise NativeError("invalid")
    # The caller supplies real new journal entries. Existing hashes and previous links cannot be silently rewritten here.
    domains.validate(tuple(entry for _, entry in original) + tuple(item.entry for item in selections))
    adopted_ids = tuple(str(uuid4()) for _ in selections)
    recorded = datetime.fromtimestamp(service.clock(), UTC).isoformat()
    decision = Reconciliation(
        expected,
        reviewed,
        tuple(Adoption(item.sources, record) for item, record in zip(selections, adopted_ids, strict=True)),
        tuple(sorted(available - accepted)),
        access.subject,
        reason,
        recorded,
    )
    record = str(uuid4())
    entries = ((record, Entry("reconciliation", as_data(decision))), *zip(adopted_ids, (item.entry for item in selections), strict=True))
    objects: list[Object] = []
    pointers = list(frontier.revisions)
    parents: tuple[str, ...] = (expected, reviewed)
    for record, entry in entries:
        payload, sealed = service.seal(access, str(uuid4()), DOMAIN, domains.encode(entry))
        objects.append(sealed)
        revision = Revision(record, entry.domain, payload, parents, operation, recorded)
        pointer, sealed = service.seal(access, record, REVISION, as_data(revision))
        pointers.append(pointer)
        objects.append(sealed)
        parents = (record,)
    refs = tuple(item for item in frontier.refs if item.name != target) + (Ref(target, record, destination.generation + 1),)
    updated = evolve(frontier, refs=tuple(sorted(refs, key=lambda item: item.name)), revisions=tuple(pointers))
    service.release(access, "review", "*", registration, started)
    return service.commit(access, operation, request, registration, updated, tuple(objects), started, permission="review")
