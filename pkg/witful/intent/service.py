"""
Persist intent projections in the existing encrypted graph scope with separate publication and review grants.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from attrs import evolve, frozen

from witful.codegraph.models import Graph
from witful.codegraph.service import RepositoryGraph, source_coverage
from witful.codegraph.snapshot import capture, read_source
from witful.exceptions import NativeError
from witful.intent.breadcrumbs import attach
from witful.intent.contracts import extends, fingerprint, review_binding, validate
from witful.intent.core import bounded, resolve
from witful.intent.draft import environment, prepare
from witful.intent.models import File, Query, Result, Review, State
from witful.knowledge.contracts import as_data
from witful.native import domains
from witful.native.context import identifier
from witful.native.models import Frontier, Receipt, Ref, Revision, parse
from witful.native.service import DOMAIN, REVISION

if TYPE_CHECKING:
    from witful.codegraph.snapshot import Snapshot
    from witful.context.models import Limits
    from witful.native.authority import Access, Registration
    from witful.repertoire.models import Inventory

DOMAIN_NAME = "repository-intent"


@frozen
class SourceResult:
    """
    Return an exact checked source range only after current admission.

    Attributes:
        anchor (str): Immutable anchor ID.
        digest (str): Whole-file digest verified before range selection.
        start (int): Inclusive byte offset.
        end (int): Exclusive byte offset.
        text (str): Exact UTF-8 source, treated as inert data.
        result (str): Source-range retrieval completeness only.
    """

    anchor: str
    digest: str
    start: int
    end: int
    text: str
    result: str = "complete"


@frozen
class IntentGraph:
    """
    Reuse graph custody, native atomic publication and fresh revocation checks.

    Attributes:
        graph (RepositoryGraph): Independently enrolled engineer-owned extension.
    """

    graph: RepositoryGraph

    def snapshot(self, access: Access, frontier: Frontier) -> tuple[Graph, Snapshot]:
        """
        Bind intent to the exact current CodeGraph without accepting an arbitrary repository.

        Args:
            access (Access): Admitted transport and grant.
            frontier (Frontier): Authenticated current native frontier.

        Returns:
            tuple[Graph, Snapshot]: Matching clean source and exact graph generation.
        """
        target = next((item for item in frontier.refs if item.name == "codegraph"), None)
        if target is None:
            raise NativeError("unavailable")
        native = self.graph.native
        metadata = native.revision(access, frontier, target.revision)
        entry = domains.decode(native.open(access, metadata.payload))
        if entry.domain != "repository-codegraph" or metadata.domain != entry.domain:
            raise NativeError("invalid")
        graph = parse(entry.value, Graph)
        snapshot = capture(self.graph.enrollment, graph.revision)
        if (
            graph.enrollment != self.graph.enrollment
            or graph.tree != snapshot.tree
            or graph.files != source_coverage(snapshot, graph.files)
            or graph.omitted_untracked != snapshot.untracked
        ):
            raise NativeError("conflict")
        return graph, snapshot

    def manifest(self, snapshot: Snapshot) -> tuple[File, ...]:
        """
        Declare every tracked byte without treating SDK ingestion as semantic reading.

        Args:
            snapshot (Snapshot): Just-verified clean approved source.

        Returns:
            tuple[File, ...]: Exact manifest including excluded and unsupported denominators.
        """
        enrollment = self.graph.enrollment
        files: list[File] = []
        for item in snapshot.files:
            raw = read_source(Path(enrollment.repository), item.path, enrollment.source_bytes)
            disposition: Literal["source", "unsupported", "excluded"] = (
                "excluded" if item.coverage == "excluded" else "unsupported" if item.coverage == "non-text" else "source"
            )
            files.append(File(item.path, hashlib.sha256(raw).hexdigest(), len(raw), disposition))
        return tuple(sorted(files, key=lambda item: item.path))

    def load(self, access: Access, frontier: Frontier) -> State | None:
        """
        Open the current authenticated intent record without exposing generic graph history.

        Args:
            access (Access): Admitted transport identity.
            frontier (Frontier): Current authenticated manifest.

        Returns:
            State | None: Existing intent source or an explicitly empty extension.
        """
        target = next((item for item in frontier.refs if item.name == "intent"), None)
        if target is None:
            return None
        native = self.graph.native
        metadata = native.revision(access, frontier, target.revision)
        entry = domains.decode(native.open(access, metadata.payload))
        if metadata.domain != DOMAIN_NAME or entry.domain != DOMAIN_NAME:
            raise NativeError("invalid")
        state = parse(entry.value, State)
        validate(state)
        return state

    def bind(self, state: State, graph: Graph, snapshot: Snapshot) -> None:
        """
        Reject scope substitution and stale anchors before publication or retrieval.

        Args:
            state (State): Proposed or authenticated intent state.
            graph (Graph): Authenticated graph generation.
            snapshot (Snapshot): Current clean tracked snapshot.

        Returns:
            None: All anchors refer to the exact permitted source universe.
        """
        enrollment = self.graph.enrollment
        if (state.scope.tenant, state.scope.owner, state.scope.repository, state.scope.revision, state.scope.graph) != (
            enrollment.tenant,
            enrollment.owner,
            enrollment.extension,
            graph.revision,
            graph.generation,
        ):
            raise NativeError("conflict")
        if state.files != self.manifest(snapshot):
            raise NativeError("conflict")
        for kind, expected in environment(graph, state.files).items():
            matches = [item.digest for item in state.inputs if item.kind == kind]
            if matches != [expected]:
                raise NativeError("conflict")
        excluded = {item.path for item in state.files if item.disposition == "excluded"}
        nodes = {item.id: item for item in graph.nodes}
        for anchor in state.anchors:
            if anchor.path in excluded:
                raise NativeError("denied")
            if anchor.symbol and (anchor.symbol not in nodes or nodes[anchor.symbol].path != anchor.path):
                raise NativeError("invalid")
        anchors = {item.id: item for item in state.anchors}
        for evidence in state.evidence:
            if evidence.source in anchors:
                anchor = anchors[evidence.source]
                raw = read_source(Path(enrollment.repository), anchor.path, enrollment.source_bytes)[anchor.start : anchor.end]
                if hashlib.sha256(raw).hexdigest() != evidence.digest:
                    raise NativeError("conflict")

    def commit(
        self,
        access: Access,
        operation: str,
        request: str,
        registration: Registration,
        frontier: Frontier,
        candidate: State,
        started: float,
        permission: str,
    ) -> Receipt:
        """
        Seal the complete candidate and atomically replace only the intent ref.

        Args:
            access (Access): Admitted peer and scope.
            operation (str): Stable retry UUID.
            request (str): Exact request digest.
            registration (Registration): Independent expected frontier.
            frontier (Frontier): Complete authenticated prior manifest.
            candidate (State): Validated complete successor.
            started (float): Original monotonic operation start.
            permission (str): Dedicated mutation permission retained for recovery.

        Returns:
            Receipt: Durable native acknowledgment, never an action authorization.
        """
        native = self.graph.native
        validate(candidate)
        native.release(access, permission, "*", registration, started)
        target = next((item for item in frontier.refs if item.name == "intent"), None)
        record = str(uuid4())
        payload, sealed = native.seal(access, str(uuid4()), DOMAIN, domains.encode(domains.Entry(DOMAIN_NAME, as_data(candidate))))
        metadata = Revision(
            record,
            DOMAIN_NAME,
            payload,
            (target.revision,) if target else (),
            operation,
            datetime.fromtimestamp(native.clock(), UTC).isoformat(),
        )
        pointer, encrypted = native.seal(access, record, REVISION, as_data(metadata))
        refs = tuple(item for item in frontier.refs if item.name != "intent") + (
            Ref("intent", record, target.generation + 1 if target else 1),
        )
        updated = evolve(frontier, refs=tuple(sorted(refs, key=lambda item: item.name)), revisions=(*frontier.revisions, pointer))
        return native.commit(
            access, operation, request, registration, updated, (sealed, encrypted), started, permission=permission, project=False
        )

    def draft(self, access: Access, inventory: Inventory, limits: Limits) -> State:
        """
        Prepare an unpublished candidate without claiming review or recording a tool use.

        Args:
            access (Access): Current read-only intent grant.
            inventory (Inventory): Explicit canonical repertoire snapshot.
            limits (Limits): Complete serialized output bounds.

        Returns:
            State: Transient unreviewed draft; no database write occurs.
        """
        import json

        native = self.graph.native
        started = native.monotonic()
        registration, frontier = self.graph.admit(access, "intent-query")
        graph, snapshot = self.snapshot(access, frontier)
        files = self.manifest(snapshot)
        now = int(native.clock())
        sources = {
            item.path: read_source(Path(self.graph.enrollment.repository), item.path, item.size)
            for item in files
            if item.disposition == "source"
        }
        result = attach(prepare(graph, files, inventory, now), sources, now)
        validate(result)
        if len(json.dumps(as_data(result), ensure_ascii=True, separators=(",", ":")).encode()) > min(limits.text_bytes, limits.tokens):
            raise NativeError("incomplete")
        if capture(self.graph.enrollment, graph.revision) != snapshot:
            raise NativeError("conflict")
        native.release(access, "intent-query", "*", registration, started)
        return result

    def publish(self, access: Access, operation: str, expected: str | None, state: State) -> Receipt:
        """
        Publish evidence without allowing a publisher to fabricate a verified review.

        Args:
            access (Access): Current intent-write grant on this graph scope.
            operation (str): Stable retry UUID.
            expected (str | None): Exact previous intent ref, or None for initial publication.
            state (State): Complete validated candidate, bound to current CodeGraph.

        Returns:
            Receipt: Atomic encrypted publication acknowledgment.
        """
        identifier(operation)
        native = self.graph.native
        started = native.monotonic()
        registration, frontier = self.graph.admit(access, "intent-write")
        request = fingerprint(("intent-publish", expected, state))
        prior = native.previous(access, operation, request)
        if prior:
            native.release(access, "intent-write", "*", registration, started)
            return prior
        target = next((item for item in frontier.refs if item.name == "intent"), None)
        if (target.revision if target else None) != expected:
            raise NativeError("conflict")
        validate(state)
        old = self.load(access, frontier)
        if old:
            extends(old, state)
        retained = old.reviews if old and old.scope == state.scope else ()
        if state.reviews != retained:
            raise NativeError("denied")
        graph, snapshot = self.snapshot(access, frontier)
        self.bind(state, graph, snapshot)
        if capture(self.graph.enrollment, graph.revision) != snapshot:
            raise NativeError("conflict")
        return self.commit(access, operation, request, registration, frontier, state, started, "intent-write")

    def review(self, access: Access, operation: str, expected: str, decision: Review) -> Receipt:
        """
        Append an authorized explicit semantic review with server-owned attribution.

        Args:
            access (Access): Current intent-review grant, separate from publication.
            operation (str): Stable review operation UUID.
            expected (str): Exact intent ref reviewed by the caller.
            decision (Review): Claim and criterion; attribution and time must be blank or zero.

        Returns:
            Receipt: Durable review acknowledgment without any change to execution authority.
        """
        identifier(operation)
        native = self.graph.native
        started = native.monotonic()
        registration, frontier = self.graph.admit(access, "intent-review")
        if decision.reviewer or decision.authority or decision.reviewed or decision.binding:
            raise NativeError("invalid")
        request = fingerprint(("intent-review", expected, decision))
        prior = native.previous(access, operation, request)
        if prior:
            native.release(access, "intent-review", "*", registration, started)
            return prior
        target = next((item for item in frontier.refs if item.name == "intent"), None)
        if target is None or target.revision != expected:
            raise NativeError("conflict")
        state = self.load(access, frontier)
        if state is None:
            raise NativeError("unavailable")
        graph, snapshot = self.snapshot(access, frontier)
        self.bind(state, graph, snapshot)
        reviewed = evolve(
            decision,
            reviewer=access.subject,
            authority=fingerprint((access.grant, access.policy, access.task)),
            reviewed=int(native.clock()),
            binding=review_binding(state, decision.assertion),
        )
        updated = evolve(state, reviews=(*state.reviews, reviewed))
        if capture(self.graph.enrollment, graph.revision) != snapshot:
            raise NativeError("conflict")
        return self.commit(access, operation, request, registration, frontier, updated, started, "intent-review")

    def query(self, access: Access, query: Query, limits: Limits) -> Result:
        """
        Resolve only admitted current state and recheck rights immediately before release.

        Args:
            access (Access): Current intent-query grant.
            query (Query): Read-only operation; client-asserted live observations are refused.
            limits (Limits): Bounded complete output and traversal.

        Returns:
            Result: Read-only qualified evidence; no durable plaintext cache is created.
        """
        native = self.graph.native
        started = native.monotonic()
        registration, frontier = self.graph.admit(access, "intent-query")
        if query.observations:
            raise NativeError("denied")
        state = self.load(access, frontier)
        if state is None:
            raise NativeError("unavailable")
        graph, snapshot = self.snapshot(access, frontier)
        self.bind(state, graph, snapshot)
        result = resolve(state, query, limits, int(native.clock()))
        if result.scope is not None:
            target = next(item for item in frontier.refs if item.name == "intent")
            result = bounded(evolve(result, generation=target.revision), limits)
        if capture(self.graph.enrollment, graph.revision) != snapshot:
            raise NativeError("conflict")
        if (native.monotonic() - started) * 1000 > limits.elapsed_ms:
            return bounded(Result("incomplete", None), limits)
        native.release(access, "intent-query", "*", registration, started)
        return result

    def source(self, access: Access, anchor_id: str, expected: str, start: int, end: int, limits: Limits) -> SourceResult:
        """
        Read one exact approved byte range without running Git filters or repository code.

        Args:
            access (Access): Current graph-scoped intent-query grant.
            anchor_id (str): Exact existing anchor ID.
            expected (str): Expected whole-file SHA-256.
            start (int): Inclusive offset inside the anchor.
            end (int): Exclusive offset inside the anchor.
            limits (Limits): Complete serialized source-response budgets.

        Returns:
            SourceResult: Exact UTF-8 content bound to the declared range and digest.
        """
        native = self.graph.native
        started = native.monotonic()
        registration, frontier = self.graph.admit(access, "intent-query")
        state = self.load(access, frontier)
        if state is None:
            raise NativeError("unavailable")
        graph, snapshot = self.snapshot(access, frontier)
        self.bind(state, graph, snapshot)
        anchor = next((item for item in state.anchors if item.id == anchor_id), None)
        if anchor is None:
            raise NativeError("denied")
        if expected != anchor.digest or not anchor.start <= start <= end <= anchor.end:
            raise NativeError("conflict")
        if end - start > min(limits.text_bytes, limits.tokens) or limits.source_reads < 1:
            raise NativeError("incomplete")
        raw = read_source(Path(self.graph.enrollment.repository), anchor.path, self.graph.enrollment.source_bytes)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise NativeError("conflict")
        try:
            result = SourceResult(anchor_id, expected, start, end, raw[start:end].decode("utf-8"))
        except UnicodeDecodeError:
            raise NativeError("invalid") from None
        import json

        if len(json.dumps(as_data(result), ensure_ascii=True).encode()) > min(limits.text_bytes, limits.tokens):
            raise NativeError("incomplete")
        if capture(self.graph.enrollment, graph.revision) != snapshot:
            raise NativeError("conflict")
        native.release(access, "intent-query", "*", registration, started)
        return result
