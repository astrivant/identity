"""
Compose per-codebase graph generations with native ciphertext storage and fresh admission.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from attrs import frozen

from witful.codegraph.models import Enrollment, Graph, validate
from witful.codegraph.query import Result, select
from witful.codegraph.snapshot import Snapshot, capture
from witful.codegraph.worker import Extraction, extract
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.domains import Entry
from witful.native.models import Frontier, Receipt, Ref, Revision, parse
from witful.native.rotation import ROTATION, rotate
from witful.native.service import DOMAIN, REVISION

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.context.models import Limits
    from witful.native.authority import Access, Registration
    from witful.native.service import Service

DOMAIN_NAME = "repository-codegraph"


@frozen
class RepositoryGraph:
    """
    Own an explicitly enrolled graph without sharing learning history or promoting code to policy.

    Attributes:
        native (Service): Existing protected runtime with independently scoped authority and key grants.
        enrollment (Enrollment): Exact settings bound by the native deployment evidence.
        worker (Callable[[Enrollment, Snapshot], Extraction]): Bounded isolated SDK worker.
    """

    native: Service
    enrollment: Enrollment
    worker: Callable[[Enrollment, Snapshot], Extraction] = extract

    def owner(self, access: Access) -> None:
        """
        Bind transport identity to the independently approved engineer runtime.

        Args:
            access (Access): Actual authenticated transport request.

        Returns:
            None: The request matches the approved scope; current grants still require admission.
        """
        enrollment = self.enrollment
        if (access.scope.tenant, access.scope.identity, access.subject) != (enrollment.tenant, enrollment.extension, enrollment.subject):
            raise NativeError("denied")
        self.native.protection()

    def admit(self, access: Access, action: str) -> tuple[Registration, Frontier]:
        """
        Check trusted runtime identity before graph selection or any key operation.

        Args:
            access (Access): Actual authenticated transport binding.
            action (str): Dedicated graph operation checked by maintained native policy evaluation.

        Returns:
            tuple[Registration, Frontier]: Independently current authority and authenticated frontier.
        """
        self.owner(access)
        registration, frontier = self.native.snapshot(access, action, "*")
        if (
            any(ref.name != "codegraph" for ref in frontier.refs)
            or any(item.kind != ROTATION for item in frontier.archives)
            or frontier.outbox
        ):
            raise NativeError("invalid")
        return registration, frontier

    def recover(self, access: Access) -> dict[str, object]:
        """
        Reconcile the exact durable pending native transaction without exposing a generic history route.

        Args:
            access (Access): Owner runtime with current recover and retained original mutation permissions.

        Returns:
            dict[str, object]: Opaque verified frontier coordinates, never source metadata.
        """
        self.owner(access)
        head = self.native.authority.recover(access, self.native.store, int(self.native.clock()))
        self.admit(access, "codegraph-query")
        return {"generation": head.generation, "root": head.root, "digest": head.digest.hex()}

    def rotate(self, access: Access, operation: str, mode: Literal["rewrap", "reseal", "resign"]) -> Receipt:
        """
        Reuse native key rotation while preserving the dedicated graph and engineer boundary.

        Args:
            access (Access): Owner runtime with independently approved write and rotate grants.
            operation (str): Stable rotation operation UUID.
            mode (Literal["rewrap", "reseal", "resign"]): Explicit current-representation transformation.

        Returns:
            Receipt: Durable receipt retaining prior ciphertext and key requirements.
        """
        self.admit(access, "rotate")
        return rotate(self.native, access, operation, mode)

    def build(self, access: Access, operation: str, revision: str, expected: str | None) -> Receipt:
        """
        Publish a complete encrypted generation using an independently fenced expected frontier.

        Args:
            access (Access): Owner runtime's authenticated request.
            operation (str): Stable retry operation UUID.
            revision (str): Exact approved checked-out Git commit.
            expected (str | None): Prior native graph revision; None enrolls an empty extension.

        Returns:
            Receipt: Durable encrypted acknowledgment, independent of remote artifact publication.
        """
        from datetime import UTC, datetime

        from witful.native.context import identifier

        identifier(operation)
        started = self.native.monotonic()
        registration, frontier = self.admit(access, "codegraph-build")
        request = hashlib.sha256(codec.encode([as_data(self.enrollment), revision, expected])).hexdigest()
        prior = self.native.previous(access, operation, request)
        if prior is not None:
            self.native.release(access, "codegraph-build", "*", registration, started)
            return prior
        target = next(iter(frontier.refs), None)
        if (target.revision if target else None) != expected:
            raise NativeError("conflict")
        if target is not None:
            from witful.native import domains

            metadata = self.native.revision(access, frontier, target.revision)
            previous = parse(domains.decode(self.native.open(access, metadata.payload)).value, Graph)
            if (previous.enrollment.repository, previous.enrollment.owner) != (self.enrollment.repository, self.enrollment.owner):
                raise NativeError("denied")
        snapshot = capture(self.enrollment, revision)
        extraction = self.worker(self.enrollment, snapshot)
        if capture(self.enrollment, revision) != snapshot:
            raise NativeError("conflict")
        record = str(uuid4())
        graph = Graph(
            self.enrollment,
            record,
            revision,
            snapshot.tree,
            snapshot.files,
            extraction.nodes,
            extraction.edges,
            extraction.indexer,
            extraction.unresolved,
            snapshot.untracked,
        )
        validate(graph)
        line_counts = {source.path: source.text.count("\n") + 1 for source in snapshot.sources}
        if any(node.end > max(1, line_counts[node.path]) for node in graph.nodes):
            raise NativeError("invalid")
        self.native.release(access, "codegraph-build", "*", registration, started)
        # Reuse native encrypted history and CAS without allowing generic journal/learning writes.
        from witful.native import domains

        payload, sealed = self.native.seal(access, str(uuid4()), DOMAIN, domains.encode(Entry(DOMAIN_NAME, as_data(graph))))
        metadata = Revision(
            record,
            DOMAIN_NAME,
            payload,
            (expected,) if expected else (),
            operation,
            datetime.fromtimestamp(self.native.clock(), UTC).isoformat(),
        )
        pointer, encrypted_metadata = self.native.seal(access, record, REVISION, as_data(metadata))
        candidate = Frontier(
            refs=(Ref("codegraph", record, target.generation + 1 if target else 1),),
            revisions=(*frontier.revisions, pointer),
            archives=frontier.archives,
        )
        return self.native.commit(
            access,
            operation,
            request,
            registration,
            candidate,
            (sealed, encrypted_metadata),
            started,
            permission="codegraph-build",
            project=False,
        )

    def query(
        self, access: Access, revision: str, symbol: str, direction: Literal["symbol", "callers", "impact"], limits: Limits, depth: int
    ) -> Result:
        """
        Decrypt only the selected current graph, then reauthorize before releasing bounded evidence.

        Args:
            access (Access): Actual admitted owner runtime.
            revision (str): Expected current source revision.
            symbol (str): Literal symbol name or local ID.
            direction (Literal["symbol", "callers", "impact"]): Explicit query operation.
            limits (Limits): Existing context output/traversal budgets.
            depth (int): Maximum relation hops.

        Returns:
            Result: Current attributed evidence; no result cache or durable plaintext is written.
        """
        from witful.native import domains

        started = self.native.monotonic()
        registration, frontier = self.admit(access, "codegraph-query")
        target = next(iter(frontier.refs), None)
        if target is None:
            raise NativeError("unavailable")
        metadata = self.native.revision(access, frontier, target.revision)
        entry = domains.decode(self.native.open(access, metadata.payload))
        if entry.domain != DOMAIN_NAME or metadata.domain != DOMAIN_NAME:
            raise NativeError("invalid")
        graph = parse(entry.value, Graph)
        snapshot = capture(self.enrollment, revision)
        if (
            graph.enrollment != self.enrollment
            or graph.revision != revision
            or graph.tree != snapshot.tree
            or graph.files != snapshot.files
            or graph.omitted_untracked != snapshot.untracked
        ):
            raise NativeError("conflict")
        result = select(graph, symbol, direction, limits, depth)
        if capture(self.enrollment, revision) != snapshot:
            raise NativeError("conflict")
        if (self.native.monotonic() - started) * 1000 > limits.elapsed_ms:
            raise NativeError("incomplete")
        self.native.release(access, "codegraph-query", "*", registration, started)
        return result
