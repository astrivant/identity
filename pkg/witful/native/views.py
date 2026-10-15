"""
Read bounded authenticated snapshots without confounding offline disclosure with live service authorization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import networkx as nx
from attrs import field, frozen

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec, domains
from witful.native.context import Context, identifier
from witful.native.kinds import DOMAIN, REVISION
from witful.native.models import Frontier, Pointer, Revision, parse

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.domains import Entry
    from witful.native.envelope import EnvelopeService
    from witful.native.service import Budget
    from witful.native.storage import Scope, Store


@frozen
class View:
    """
    Inspect one explicit ciphertext source using supplied custody, recording every authenticated representation read.

    This reader grants no live access. Service admission and result release surround
    online use; offline use requires a separately verified signed disclosure package.

    Attributes:
        scope (Scope): Independently expected immutable identity scope.
        store (Store): Explicit ciphertext source, including a read-only recovery snapshot.
        keys (EnvelopeService): Current request custody or recipient-only offline custody.
        budget (Budget): Work and memory limits for this inspection.
        monotonic (Callable[[], float]): Caller-owned elapsed-time observation.
        observed (dict[str, Pointer]): Reader-owned inventory of verified pointers, never a permission cache.
    """

    scope: Scope
    store: Store = field(repr=False)
    keys: EnvelopeService = field(repr=False)
    budget: Budget
    monotonic: Callable[[], float] = field(repr=False)
    observed: dict[str, Pointer] = field(factory=dict, init=False, repr=False)

    def open(self, pointer: Pointer) -> object:
        """
        Verify an explicitly selected pointer before recording its context or releasing its decoded value.

        Args:
            pointer (Pointer): Reference from a trusted manifest, not a storage-supplied context.

        Returns:
            object: Authenticated bounded value, still requiring its domain validation.
        """
        identifier(pointer.record)
        previous = self.observed.get(pointer.object)
        if previous is not None and previous != pointer:
            raise NativeError("invalid")
        item = self.store.get(self.scope, (pointer.object,))[0]
        if item.digest.hex() != pointer.digest:
            raise NativeError("invalid")
        context = Context(self.scope.tenant, self.scope.identity, pointer.record, pointer.kind)
        value = self.keys.open(context, item.payload)
        self.observed[pointer.object] = pointer
        return value

    def revision(self, frontier: Frontier, record: str) -> Revision:
        """
        Resolve an exact logical revision without accepting caller-supplied ciphertext coordinates.

        Args:
            frontier (Frontier): Current authenticated manifest.
            record (str): Logical revision UUID.

        Returns:
            Revision: Authenticated native metadata.
        """
        pointer = next((item for item in frontier.revisions if item.record == record), None)
        if pointer is None or pointer.kind != REVISION:
            raise NativeError("denied")
        revision = parse(self.open(pointer), Revision)
        if revision.id != record or revision.payload.kind != DOMAIN:
            raise NativeError("invalid")
        return revision

    def lineage(self, frontier: Frontier, record: str) -> tuple[tuple[Revision, Entry], ...]:
        """
        Materialize a bounded first-parent view while validating all ordered ancestry edges as a DAG.

        Args:
            frontier (Frontier): Authenticated manifest.
            record (str): Selected native head.

        Returns:
            tuple[tuple[Revision, Entry], ...]: Selected causal records in chronological order.
        """
        started = self.monotonic()
        metadata_bytes = 0
        graph: nx.DiGraph[str, dict[str, object], dict[str, object]] = nx.DiGraph()
        revisions: dict[str, Revision] = {}
        pending = [record]
        while pending:
            if self.monotonic() - started > self.budget.seconds:
                raise NativeError("incomplete")
            current = pending.pop()
            if current in revisions:
                continue
            if len(revisions) >= self.budget.revisions:
                raise NativeError("incomplete")
            revision = self.revision(frontier, current)
            metadata_bytes += len(codec.encode(as_data(revision)))
            if metadata_bytes > self.budget.bytes:
                raise NativeError("incomplete")
            if len(set(revision.parents)) != len(revision.parents):
                raise NativeError("invalid")
            revisions[current] = revision
            graph.add_node(current)
            for parent in revision.parents:
                graph.add_edge(parent, current)
                pending.append(parent)
        if not nx.is_directed_acyclic_graph(graph):
            raise NativeError("invalid")
        selected: list[tuple[Revision, Entry]] = []
        size = 0
        current = record
        while current:
            if self.monotonic() - started > self.budget.seconds:
                raise NativeError("incomplete")
            revision = revisions[current]
            payload = self.open(revision.payload)
            size += len(codec.encode(payload))
            if size > self.budget.bytes:
                raise NativeError("incomplete")
            entry = domains.decode(payload)
            if entry.domain != revision.domain:
                raise NativeError("invalid")
            selected.append((revision, entry))
            current = revision.parents[0] if revision.parents else ""
        return tuple(reversed(selected))
