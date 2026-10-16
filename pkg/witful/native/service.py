"""
Orchestrate native domain operations, authenticated history and durable receipts across interchangeable ciphertext stores.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from attrs import evolve, field, frozen

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec, domains
from witful.native.context import Context, identifier
from witful.native.kinds import DOMAIN, FRONTIER, ORIGINAL, RECEIPT, REVISION
from witful.native.models import Frontier, Pointer, Receipt, Ref, Revision, parse
from witful.native.projection.models import Policy
from witful.native.storage import Batch, Object
from witful.native.views import View

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.authority import Access, Authority, Registration
    from witful.native.domains import Entry
    from witful.native.envelope import EnvelopeService
    from witful.native.storage import Store

__all__ = ["Budget", "Service", "DOMAIN", "FRONTIER", "ORIGINAL", "RECEIPT", "REVISION"]


@frozen
class Budget:
    """
    Bound complete operations without silently returning partial history or search results.

    Attributes:
        revisions (int): Maximum authorized history nodes in one operation.
        refs (int): Maximum logical branch and tag count.
        seconds (float): Maximum elapsed service time before refusing a result or new commit.
        bytes (int): Maximum cumulative decrypted bytes in one operation.
    """

    revisions: int = 4096
    refs: int = 256
    seconds: float = 30.0
    bytes: int = 64 * 1024 * 1024

    def __attrs_post_init__(self) -> None:
        """
        Require positive finite configured resource bounds.

        Returns:
            None: Resource settings are valid.
        """
        import math

        if any(type(value) is not int or value < 1 for value in (self.revisions, self.refs, self.bytes)):
            raise NativeError("invalid")
        if not math.isfinite(self.seconds) or self.seconds <= 0:
            raise NativeError("invalid")


@frozen
class Service:
    """
    Keep domain validation and key use outside persistence transactions, with fresh checks before releasing results.

    Attributes:
        store (Store): Registered ciphertext persistence adapter.
        authority (Authority): Independently administered authorization and fencing boundary.
        keys (Callable[[Access], EnvelopeService]): Request-bound broker client factory with independent signing pins.
        protection (Callable[[], None]): Current independently verified deployment protection boundary.
        budget (Budget): Explicit service work limits.
        clock (Callable[[], float]): UTC epoch observation boundary.
        monotonic (Callable[[], float]): Elapsed-time boundary for bounded operations.
        projection (Policy): Explicit durable outbox and remote-verification policy, disabled by default.
        graph_scopes (tuple[tuple[str, str], ...]): Reserved extension scopes excluded from generic HTTP operations.
    """

    store: Store = field(repr=False)
    authority: Authority = field(repr=False)
    keys: Callable[[Access], EnvelopeService] = field(repr=False)
    protection: Callable[[], None] = field(repr=False)
    budget: Budget = Budget()
    clock: Callable[[], float] = time.time
    monotonic: Callable[[], float] = time.monotonic
    projection: Policy = Policy()
    graph_scopes: tuple[tuple[str, str], ...] = ()

    def seal(self, access: Access, record: str, kind: int, value: object) -> tuple[Pointer, Object]:
        """
        Produce a fresh independently signed representation without changing logical identity.

        Args:
            access (Access): Admitted request bindings.
            record (str): Immutable logical UUID.
            kind (int): Closed native discriminator.
            value (object): Bounded typed native payload.

        Returns:
            tuple[Pointer, Object]: Protected manifest reference and sealed persistent bytes.
        """
        context = Context(access.scope.tenant, access.scope.identity, record, kind)
        item = Object(str(uuid4()), self.keys(access).seal(context, value))
        return Pointer(record, item.id, kind, item.digest.hex()), item

    def open(self, access: Access, pointer: Pointer) -> object:
        """
        Resolve only an independently authorized manifest pointer and authenticate before returning plaintext.

        Args:
            access (Access): Admitted scope and key bindings.
            pointer (Pointer): Trusted reference from the current authenticated frontier.

        Returns:
            object: Authenticated bounded native value; callers still perform result-release authorization.
        """
        return self.view(access).open(pointer)

    def view(self, access: Access) -> View:
        """
        Compose an explicit inspection boundary after the calling operation has established authorization.

        Args:
            access (Access): Request-bound key context; constructing a reader does not grant live access.

        Returns:
            View: Bounded reader shared with independent signed-export verification.
        """
        return View(access.scope, self.store, self.keys(access), self.budget, self.monotonic)

    def snapshot(self, access: Access, action: str, record: str) -> tuple[Registration, Frontier]:
        """
        Bind all subsequent reads to the independently acknowledged frontier instead of trusting restored storage metadata.

        Args:
            access (Access): Authenticated request.
            action (str): Requested policy operation.
            record (str): Logical record or whole-identity target.

        Returns:
            tuple[Registration, Frontier]: Current authority and authenticated complete logical ref snapshot.
        """
        self.protection()
        registration = self.authority.check(access, action, record, int(self.clock()))
        if self.store.head(access.scope) != registration.head:
            raise NativeError("conflict")
        head = registration.head
        if head.root is None:
            return registration, Frontier()
        value = self.open(access, Pointer(head.root, head.root, FRONTIER, head.digest.hex()))
        frontier = parse(value, Frontier)
        if frontier.version != 1 or len(frontier.refs) > self.budget.refs or len(frontier.revisions) > self.budget.revisions:
            raise NativeError("incomplete")
        if len({item.name for item in frontier.refs}) != len(frontier.refs):
            raise NativeError("invalid")
        if len({item.record for item in frontier.revisions}) != len(frontier.revisions):
            raise NativeError("invalid")
        return registration, frontier

    def release(self, access: Access, action: str, record: str, registration: Registration, started: float) -> None:
        """
        Reject revoked, migrated, stale or over-budget results immediately before releasing them.

        Args:
            access (Access): Original authenticated request.
            action (str): Requested permission.
            record (str): Original target.
            registration (Registration): Admitted independent frontier.
            started (float): Monotonic operation start.

        Returns:
            None: The original admission still holds at this release boundary.
        """
        self.protection()
        if self.monotonic() - started > self.budget.seconds:
            raise NativeError("incomplete")
        if self.authority.check(access, action, record, int(self.clock())) != registration:
            raise NativeError("conflict")

    def revision(self, access: Access, frontier: Frontier, record: str) -> Revision:
        """
        Resolve an exact logical revision without accepting caller-supplied ciphertext coordinates.

        Args:
            access (Access): Admitted scope.
            frontier (Frontier): Current authenticated manifest.
            record (str): Logical revision UUID.

        Returns:
            Revision: Authenticated native metadata.
        """
        return self.view(access).revision(frontier, record)

    def read(self, access: Access, record: str) -> Entry:
        """
        Read one domain revision under record-scoped authorization and fresh result-release checks.

        Args:
            access (Access): Authenticated request.
            record (str): Exact logical UUID.

        Returns:
            Entry: One validated domain payload.
        """
        started = self.monotonic()
        registration, frontier = self.snapshot(access, "read", identifier(record))
        revision = self.revision(access, frontier, record)
        result = domains.decode(self.open(access, revision.payload))
        if result.domain != revision.domain:
            raise NativeError("invalid")
        self.release(access, "read", record, registration, started)
        return result

    def lineage(self, access: Access, frontier: Frontier, record: str) -> tuple[tuple[Revision, Entry], ...]:
        """
        Materialize a bounded first-parent view while validating all ordered ancestry edges as a DAG.

        Args:
            access (Access): Whole-identity traversal or write admission.
            frontier (Frontier): Authenticated manifest.
            record (str): Selected native head.

        Returns:
            tuple[tuple[Revision, Entry], ...]: Selected causal records in chronological order.
        """
        return self.view(access).lineage(frontier, record)

    def history(self, access: Access, ref: str) -> tuple[tuple[Revision, Entry], ...]:
        """
        Return a complete selected branch view, requiring explicit traversal of the whole identity.

        Args:
            access (Access): Authenticated whole-identity traversal grant.
            ref (str): Exact meaningful ref name, kept out of persistence routing and metrics.

        Returns:
            tuple[tuple[Revision, Entry], ...]: Complete bounded branch state.
        """
        started = self.monotonic()
        registration, frontier = self.snapshot(access, "traverse", "*")
        target = next((item for item in frontier.refs if item.name == ref), None)
        if target is None:
            raise NativeError("denied")
        result = self.lineage(access, frontier, target.revision)
        domains.validate(tuple(entry for _, entry in result))
        self.release(access, "traverse", "*", registration, started)
        return result

    def search(self, access: Access, ref: str, query: str) -> tuple[str, ...]:
        """
        Search an authorized bounded in-memory view without writing plaintext or blinded indexes.

        Args:
            access (Access): Authenticated traversal grant.
            ref (str): Selected branch.
            query (str): Nonempty literal query, never logged or retained.

        Returns:
            tuple[str, ...]: Matching logical revision IDs; budget exhaustion raises incomplete rather than truncating.
        """
        if not query or len(query.encode()) > 4096:
            raise NativeError("invalid")
        # The domain tree, not serialized CBOR bytes or public semantic digests, supplies searchable text.
        result: list[str] = []
        started = self.monotonic()
        registration = self.authority.check(access, "traverse", "*", int(self.clock()))
        for revision, entry in self.history(access, ref):
            pending = [entry.value]
            matched = False
            while pending:
                value = pending.pop()
                if isinstance(value, str):
                    matched |= query.casefold() in value.casefold()
                elif isinstance(value, dict):
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
            if matched:
                result.append(revision.id)
        self.release(access, "traverse", "*", registration, started)
        return tuple(result)

    def previous(self, access: Access, operation: str, request: str) -> Receipt | None:
        """
        Resolve an identical logical retry using its encrypted semantic binding.

        Args:
            access (Access): Currently admitted writer.
            operation (str): Stable caller operation UUID.
            request (str): Semantic request digest retained only within the encrypted receipt.

        Returns:
            Receipt | None: Original receipt or no observed commit; changed input is a conflict.
        """
        item = self.store.receipt(access.scope, operation)
        if item is None:
            return None
        receipt = parse(
            self.keys(access).open(Context(access.scope.tenant, access.scope.identity, operation, RECEIPT), item.payload), Receipt
        )
        if receipt.version != 1 or receipt.operation != operation or receipt.request != request:
            raise NativeError("conflict")
        return receipt

    def candidate(
        self,
        access: Access,
        operation: str,
        request: str,
        registration: Registration,
        frontier: Frontier,
        objects: tuple[Object, ...],
        remote_required: bool = False,
    ) -> tuple[Batch, Receipt]:
        """
        Seal an exact candidate outside locks without making it authoritative or publishing any effect.

        Args:
            access (Access): Admitted request and intended receipt epoch.
            operation (str): Stable caller operation UUID.
            request (str): Encrypted semantic request binding.
            registration (Registration): Expected committed source frontier.
            frontier (Frontier): Complete candidate metadata.
            objects (tuple[Object, ...]): Newly sealed records.
            remote_required (bool): Retained completion requirement accompanying this accepted operation.

        Returns:
            tuple[Batch, Receipt]: Immutable prepared bytes and their logical acknowledgment.
        """
        if len(frontier.revisions) > self.budget.revisions or len(frontier.refs) > self.budget.refs:
            raise NativeError("incomplete")
        old = registration.head
        previous = Pointer(old.root, old.root, FRONTIER, old.digest.hex()) if old.root is not None else None
        frontier = evolve(frontier, previous=previous)
        root_id = str(uuid4())
        context = Context(access.scope.tenant, access.scope.identity, root_id, FRONTIER)
        root = Object(root_id, self.keys(access).seal(context, as_data(frontier)))
        pointer = Pointer(root_id, root_id, FRONTIER, root.digest.hex())
        receipt = Receipt(1, operation, request, access.epoch, access.policy, old.generation + 1, pointer, "durable", remote_required)
        _, sealed = self.seal(access, operation, RECEIPT, as_data(receipt))
        pending = {item.object for item in frontier.outbox}
        outbox = tuple(item for item in objects if item.id in pending)
        retained = tuple(item for item in objects if item.id not in pending)
        return Batch(operation, old, root, retained, sealed, outbox), receipt

    def commit(
        self,
        access: Access,
        operation: str,
        request: str,
        registration: Registration,
        frontier: Frontier,
        objects: tuple[Object, ...],
        started: float,
        permission: str = "write",
        project: bool = True,
        requirements: tuple[str, ...] = (),
    ) -> Receipt:
        """
        Seal a complete frontier and receipt before the durable prepare and final fenced commit.

        Args:
            access (Access): Current authenticated writer.
            operation (str): Stable logical operation UUID.
            request (str): Protected semantic request digest.
            registration (Registration): Expected current authority snapshot.
            frontier (Frontier): Complete candidate refs and retained pointers.
            objects (tuple[Object, ...]): Newly sealed individual domain and metadata records.
            started (float): Operation start for bounded work.
            permission (str): Additional action rechecked at the durable prepare, apply and response boundaries.
            project (bool): Queue configured projection with this logical mutation; internal projection bookkeeping passes False.
            requirements (tuple[str, ...]): Current permissions retained in durable preparation, including internal delivery updates.

        Returns:
            Receipt: Durable native acknowledgment, distinct from remote Git verification.
        """
        from witful.native.projection.intents import enqueue

        if project and self.projection.select(access.scope.tenant, access.scope.identity):
            frontier, objects = enqueue(self, access, operation, registration, frontier, objects)
            requirements = tuple(dict.fromkeys((*requirements, "project", "export")))
        remote_required = bool(
            project and self.projection.mode == "required" and self.projection.select(access.scope.tenant, access.scope.identity)
        )
        batch, receipt = self.candidate(access, operation, request, registration, frontier, objects, remote_required)
        self.release(access, "write", "*", registration, started)
        self.authority.prepare(access, batch, int(self.clock()), permission, requirements)
        self.authority.apply(access, self.store, int(self.clock()))
        # A policy change after commit can deny the response without undoing the durable receipt.
        self.protection()
        with self.authority.guard(access, "write", "*", int(self.clock()), (permission, *requirements)):
            pass
        return receipt

    def append(
        self, access: Access, operation: str, ref: str, expected: str | None, entries: tuple[Entry, ...], original: bytes | None = None
    ) -> Receipt:
        """
        Append individually typed records under an explicit expected branch head and one atomic frontier CAS.

        Args:
            access (Access): Authenticated whole-identity writer.
            operation (str): Stable retry UUID.
            ref (str): Destination branch name.
            expected (str | None): Exact expected logical head; None creates an absent branch.
            entries (tuple[Entry, ...]): Ordered records validated together with preserved causal history.
            original (bytes | None): Exact optional imported representation, encrypted separately.

        Returns:
            Receipt: Durable operation receipt; an identical retry returns its original target.
        """
        started = self.monotonic()
        identifier(operation)
        if not ref or len(ref.encode()) > 1024 or not entries or len(entries) > self.budget.revisions:
            raise NativeError("invalid")
        if any(entry.domain == "reconciliation" for entry in entries):
            raise NativeError("denied")
        request = hashlib.sha256(
            b"witful-native-append-v1\0"
            + codec.encode(
                [ref, expected, [domains.encode(entry) for entry in entries], original],
                codec.Limits(bytes=self.budget.bytes, items=200_000),
            )
        ).hexdigest()
        registration, frontier = self.snapshot(access, "write", "*")
        prior = self.previous(access, operation, request)
        if prior is not None:
            self.release(access, "write", "*", registration, started)
            return prior
        branch = next((item for item in frontier.refs if item.name == ref), None)
        if (branch.revision if branch else None) != expected or (branch is not None and branch.immutable):
            raise NativeError("conflict")
        history = self.lineage(access, frontier, expected) if expected is not None else ()
        domains.validate(tuple(entry for _, entry in history) + entries)
        objects: list[Object] = []
        pointers = list(frontier.revisions)
        source = None
        if original is not None:
            source, sealed = self.seal(access, str(uuid4()), ORIGINAL, original)
            objects.append(sealed)
        head = expected
        recorded = datetime.fromtimestamp(self.clock(), UTC).isoformat()
        for entry in entries:
            record = str(uuid4())
            payload, sealed = self.seal(access, str(uuid4()), DOMAIN, domains.encode(entry))
            objects.append(sealed)
            revision = Revision(record, entry.domain, payload, (head,) if head is not None else (), operation, recorded, source)
            pointer, sealed = self.seal(access, record, REVISION, as_data(revision))
            pointers.append(pointer)
            objects.append(sealed)
            head = record
        assert head is not None
        target = Ref(ref, head, branch.generation + 1 if branch else 1)
        refs = tuple(item for item in frontier.refs if item.name != ref) + (target,)
        frontier = evolve(frontier, refs=tuple(sorted(refs, key=lambda item: item.name)), revisions=tuple(pointers))
        return self.commit(access, operation, request, registration, frontier, tuple(objects), started)

    def branch(self, access: Access, operation: str, name: str, record: str, immutable: bool = False) -> Receipt:
        """
        Create an absent branch or retained tag without altering source history.

        Args:
            access (Access): Current whole-identity writer.
            operation (str): Stable operation UUID.
            name (str): New unique meaningful name.
            record (str): Existing admitted logical revision.
            immutable (bool): Whether the new ref is a retained immutable tag.

        Returns:
            Receipt: Durable ref-creation acknowledgment.
        """
        started = self.monotonic()
        identifier(operation)
        identifier(record)
        if not name or len(name.encode()) > 1024:
            raise NativeError("invalid")
        request = hashlib.sha256(b"witful-native-branch-v1\0" + codec.encode([name, record, immutable])).hexdigest()
        registration, frontier = self.snapshot(access, "write", "*")
        prior = self.previous(access, operation, request)
        if prior is not None:
            self.release(access, "write", "*", registration, started)
            return prior
        if any(item.name == name for item in frontier.refs):
            raise NativeError("conflict")
        self.revision(access, frontier, record)
        frontier = evolve(frontier, refs=tuple(sorted((*frontier.refs, Ref(name, record, 1, immutable)), key=lambda item: item.name)))
        return self.commit(access, operation, request, registration, frontier, (), started)
