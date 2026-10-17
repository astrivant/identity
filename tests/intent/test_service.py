"""
Verify intent custody against real Git/PostgreSQL storage, maintained policy evaluation and ciphertext.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import evolve
from witful.codegraph.service import RepositoryGraph
from witful.codegraph.worker import Extraction
from witful.context.models import Limits
from witful.exceptions import NativeError
from witful.intent.contracts import fingerprint, review_binding
from witful.intent.draft import prepare as draft
from witful.intent.models import Anchor, Assertion, Evidence, Query, Review, Scope, State
from witful.intent.service import IntentGraph
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.api.admission import Admission
from witful.native.api.builder import Builder
from witful.native.wire import encode_batch

from tests.codegraph.support import repository
from tests.intent.support import example
from tests.native.requests import body

if TYPE_CHECKING:
    from pathlib import Path

    from witful.codegraph.models import Enrollment
    from witful.codegraph.snapshot import Snapshot
    from witful.intent.models import Result
    from witful.native.authority import Access, Registration
    from witful.native.models import Receipt

    from tests.native.database import Databases
    from tests.native.runtime import Runtime

LIMITS = Limits(tokens=100000, elapsed_ms=30000)


def extraction(enrollment: Enrollment, snapshot: Snapshot) -> Extraction:
    """
    Keep the SDK seam synthetic while exercising real custody and storage.

    Args:
        enrollment (Enrollment): Exact test enrollment.
        snapshot (Snapshot): Verified fixture source.

    Returns:
        Extraction: Valid empty topology with explicit unresolved evidence.
    """
    assert enrollment.repository and snapshot.sources
    return Extraction((), (), "synthetic", 1)


def prepare(runtime: Runtime, databases: Databases, path: Path) -> tuple[IntentGraph, State]:
    """
    Build an actual protected graph and bind a synthetic candidate to its source.

    Args:
        runtime (Runtime): Real native backend and synthetic grant.
        databases (Databases): Independently provisioned authority database.
        path (Path): Disposable clean repository path.

    Returns:
        tuple[IntentGraph, State]: Ready graph and unreviewed publication candidate.
    """
    enrollment, revision = repository(path)
    access = runtime.access
    enrollment = evolve(enrollment, tenant=access.scope.tenant, extension=access.scope.identity, subject=access.subject)
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute(
            "UPDATE witful_native_grants SET actions=ARRAY['write','codegraph-build','codegraph-query',"
            "'intent-write','intent-query','intent-review','rotate','recover'] WHERE id=%s",
            (access.grant,),
        )
    graph = RepositoryGraph(runtime.service, enrollment, extraction)
    graph.build(access, str(uuid4()), revision, None)
    service = IntentGraph(graph)
    _, frontier = graph.admit(access, "intent-write")
    source, snapshot = service.snapshot(access, frontier)
    files = service.manifest(snapshot)
    file = next(item for item in files if item.path == "sample.py")
    base = example()
    scope = Scope(enrollment.tenant, enrollment.owner, enrollment.extension, revision, fingerprint(files), source.generation)
    evidence = Evidence("source:1", "runtime_observation", "anchor:1", file.digest, "fixture", 100, ("anchor:1",))
    declaration = Evidence("contract:1", "intent_declaration", "specification:synthetic", "b" * 64, "synthetic-maintainer", 100, ())
    claim = Assertion(
        "claim:1",
        "tool:publish",
        ("anchor:1",),
        "Synthetic candidate",
        "fixture only",
        "inference",
        (evidence.id, declaration.id),
        (),
        (),
        (),
        100,
    )
    # Keep every required environment binding, including parsers added after the synthetic example.
    bound_inputs = draft(source, files, base.inventory, 100).inputs
    state = evolve(
        base,
        inputs=bound_inputs,
        scope=scope,
        files=files,
        anchors=(Anchor("anchor:1", file.path, file.digest, 0, file.size, "synthetic", "bytes"),),
        coverage=(),
        evidence=(evidence, declaration),
        assertions=(claim,),
    )
    return service, state


def test_publication_review_custody(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Keep published candidates unverified until an independently granted review is appended.

    Args:
        runtime (Runtime): Actual Git or PostgreSQL ciphertext store.
        databases (Databases): Separate synthetic authority.
        tmp_path (Path): Disposable repository directory.

    Returns:
        None: Review, retry, source, rotation and generic-route fences preserve scope.
    """
    service, state = prepare(runtime, databases, tmp_path / "source")
    access = runtime.access
    operation = str(uuid4())
    parser = next(item for item in state.inputs if item.kind == "documentation-parser")
    with pytest.raises(NativeError, match="conflict"):
        service.publish(access, operation, None, evolve(state, inputs=tuple(item for item in state.inputs if item != parser)))
    receipt = service.publish(access, operation, None, state)
    assert service.publish(access, operation, None, state) == receipt
    result = service.query(access, Query("find"), LIMITS)
    assert result.claims[0].projection == "inferred"
    _, frontier = service.graph.admit(access, "intent-review")
    revision = next(item.revision for item in frontier.refs if item.name == "intent")
    decision = Review("review:1", "claim:1", "declared-intent/1", ("contract:1",), "supported", "Synthetic semantic decision", "", "", 0)
    operation = str(uuid4())
    approved = service.review(access, operation, revision, decision)
    assert service.review(access, operation, revision, decision) == approved
    result = service.query(access, Query("find", view="verified"), LIMITS)
    assert result.claims[0].projection == "verified" and result.reviews[0].reviewer == access.subject
    assert result.execution_authority == "not-evaluated"
    anchor = state.anchors[0]
    source = service.source(access, anchor.id, anchor.digest, anchor.start, anchor.end, LIMITS)
    assert source.text == (tmp_path / "source/sample.py").read_text()
    service.graph.rotate(access, str(uuid4()), "resign")
    assert service.query(access, Query("find", view="verified"), LIMITS) == result
    for batch in runtime.service.store.history(access.scope):
        ciphertext = encode_batch(batch, codec.DEFAULT_LIMITS)
        assert b"Synthetic candidate" not in ciphertext and b"sample.py" not in ciphertext
    # The existing generic routes must not become an export bypass for the newly stored intent domain.
    reserved = evolve(runtime.service, graph_scopes=((access.scope.tenant, access.scope.identity),))
    app = Builder(reserved, Admission(1), lambda: True, lambda: access.subject, codegraphs=(service.graph.enrollment,)).build()
    response = app.test_client().post(
        "/v1/intent-query",
        data=body(runtime, {"query": as_data(Query("find")), "limits": as_data(LIMITS)}),
        content_type="application/cbor",
    )
    assert response.status_code == HTTPStatus.OK
    response = app.test_client().post("/v1/history", data=body(runtime, {"ref": "intent"}), content_type="application/cbor")
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_source_intent_survives_new_facade(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Retrieve stored ordinary-code intent from a new facade without the publishing caller's state.

    Args:
        runtime (Runtime): Actual Git or PostgreSQL ciphertext store.
        databases (Databases): Independent synthetic authority.
        tmp_path (Path): Disposable clean repository.

    Returns:
        None: Fresh facade objects retrieve the same persisted source assertion and generation.
    """
    writer, candidate = prepare(runtime, databases, tmp_path / "source")
    claim = evolve(candidate.assertions[0], tool="", statement="The sample module preserves its declared interface.")
    candidate = evolve(candidate, assertions=(claim,))
    writer.publish(runtime.access, str(uuid4()), None, candidate)
    expected = writer.query(runtime.access, Query("explain", claim.id), LIMITS)

    # Recreate the query boundary so retrieval cannot depend on a facade-local candidate cache.
    reader = IntentGraph(RepositoryGraph(runtime.service, writer.graph.enrollment, extraction))
    actual = reader.query(runtime.access, Query("explain", claim.id), LIMITS)
    assert actual == expected and actual.claims[0].assertion == claim
    assert actual.claims[0].entrypoint == "" and actual.generation


def test_denials_and_atomicity(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Refuse forged reviewers, mismatched scopes, stale sources and revoked access without partial publication.

    Args:
        runtime (Runtime): Actual ciphertext backend.
        databases (Databases): Independent synthetic authority.
        tmp_path (Path): Test-only workspace.

    Returns:
        None: No rejected candidate becomes the current intent view.
    """
    service, state = prepare(runtime, databases, tmp_path / "source")
    access = runtime.access
    forged = Review("review:1", "claim:1", "intent/1", ("contract:1",), "supported", "Self-approved", "a" * 64, "forged", 100)
    forged = evolve(forged, binding=review_binding(state, forged.assertion))
    with pytest.raises(NativeError):
        service.publish(access, str(uuid4()), None, evolve(state, reviews=(forged,)))
    with pytest.raises(NativeError):
        service.publish(access, str(uuid4()), None, evolve(state, scope=evolve(state.scope, owner=str(uuid4()))))
    service.publish(access, str(uuid4()), None, state)
    with pytest.raises(NativeError):
        service.publish(access, str(uuid4()), None, state)
    with pytest.raises(NativeError):
        service.query(evolve(access, subject="b" * 64), Query("find"), LIMITS)
    (tmp_path / "source/sample.py").write_text("dirty = True\n")
    with pytest.raises(NativeError):
        service.query(access, Query("find"), LIMITS)
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("DELETE FROM witful_native_grants WHERE id=%s", (access.grant,))
    with pytest.raises(NativeError):
        service.query(access, Query("find"), LIMITS)
    assert runtime.service.store.head(access.scope).generation == 2


def test_refresh_preserves_history_and_requires_rebinding(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Keep encrypted prior intent while refusing it as current evidence after a graph refresh.

    Args:
        runtime (Runtime): Real ciphertext backend.
        databases (Databases): Separate synthetic authority.
        tmp_path (Path): Disposable source workspace.

    Returns:
        None: A new complete candidate replaces only the intent ref and retains native ancestry.
    """
    service, state = prepare(runtime, databases, tmp_path / "source")
    access = runtime.access
    service.publish(access, str(uuid4()), None, state)
    before = service.query(access, Query("find"), LIMITS)
    _, frontier = service.graph.admit(access, "codegraph-build")
    old_graph = next(item.revision for item in frontier.refs if item.name == "codegraph")
    service.graph.build(access, str(uuid4()), state.scope.revision, old_graph)
    with pytest.raises(NativeError, match="conflict"):
        service.query(access, Query("find"), LIMITS)
    draft = service.draft(access, state.inventory, LIMITS)
    assert not draft.reviews and not draft.coverage
    service.publish(access, str(uuid4()), before.generation, draft)
    current = service.query(access, Query("find"), LIMITS)
    assert current.claims[0].projection == "inferred"
    _, frontier = service.graph.admit(access, "intent-query")
    history = runtime.service.lineage(access, frontier, current.generation)
    assert len(history) == 2 and history[0][0].id != history[1][0].id


def test_concurrent_intent_publication(runtime: Runtime, databases: Databases, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Force two candidates to compete at the same native expected-generation boundary.

    Args:
        runtime (Runtime): Real native ciphertext backend.
        databases (Databases): Independent durable authority.
        tmp_path (Path): Disposable source.
        monkeypatch (pytest.MonkeyPatch): Deterministic test-only synchronization seam.

    Returns:
        None: Exactly one complete intent state is published and its source remains queryable.
    """
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from witful.native.service import Service

    service, state = prepare(runtime, databases, tmp_path / "source")
    original = Service.previous
    barrier = Barrier(2, timeout=20)

    def previous(self: Service, access: Access, operation: str, request: str) -> Receipt | None:
        """
        Synchronize only after both candidates have acquired their initial snapshot.

        Args:
            self (Service): Actual tested service.
            access (Access): Synthetic caller.
            operation (str): Retry UUID.
            request (str): Exact request digest.

        Returns:
            Receipt | None: Original replay result.
        """
        result = original(self, access, operation, request)
        barrier.wait()
        return result

    monkeypatch.setattr(Service, "previous", previous)

    def publish() -> tuple[str, str]:
        """
        Retain the stable operation ID alongside the actual transaction outcome.

        Returns:
            tuple[str, str]: Operation ID and durable, conflicting or unsettled status.
        """
        operation = str(uuid4())
        try:
            service.publish(runtime.access, operation, None, state)
            return operation, "durable"
        except NativeError as error:
            return operation, error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: publish(), range(2)))
    assert sum(status == "durable" for _, status in outcomes) == 1
    # A competing writer can observe the winner's durable prepare before its acknowledgment.
    assert {status for _, status in outcomes} <= {"durable", "conflict", "unknown"}
    monkeypatch.undo()
    assert service.graph.recover(runtime.access)["generation"] == 2
    request = fingerprint(("intent-publish", None, state))
    receipts = [original(runtime.service, runtime.access, operation, request) for operation, _ in outcomes]
    assert sum(receipt is not None for receipt in receipts) == 1
    assert service.query(runtime.access, Query("find"), LIMITS).result == "complete"


def test_result_release_rechecks_revocation(
    runtime: Runtime, databases: Databases, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Revoke a query grant after resolution to prove the final response boundary remains live.

    Args:
        runtime (Runtime): Real ciphertext backend and synthetic peer.
        databases (Databases): Separate policy database.
        tmp_path (Path): Disposable source.
        monkeypatch (pytest.MonkeyPatch): Deterministic boundary fault injection.

    Returns:
        None: No resolved private result is released after the grant is revoked.
    """
    from witful.intent import service as module
    from witful.intent.core import resolve

    service, state = prepare(runtime, databases, tmp_path / "source")
    access = runtime.access
    service.publish(access, str(uuid4()), None, state)
    original = resolve

    def revoke(candidate: State, query: Query, limits: Limits, now: int) -> Result:
        """
        Resolve normally, then revoke before the service can release that result.

        Args:
            candidate (State): Actual decrypted fixture state.
            query (Query): Literal read-only request.
            limits (Limits): Query budget.
            now (int): Injected service observation time.

        Returns:
            Result: Complete result that the service must withhold.
        """
        result = original(candidate, query, limits, now)
        with psycopg.connect(databases.authority_admin) as admin:
            admin.execute("DELETE FROM witful_native_grants WHERE id=%s", (access.grant,))
        return result

    monkeypatch.setattr(module, "resolve", revoke)
    with pytest.raises(NativeError, match="denied"):
        service.query(access, Query("find"), LIMITS)


@pytest.mark.parametrize("operation", ["draft", "query", "source"])
def test_read_deadline_includes_authority_release(
    runtime: Runtime, databases: Databases, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """
    Expire the requested budget during final authorization without sleeping or changing grants.

    Args:
        runtime (Runtime): Actual encrypted Git or PostgreSQL backend.
        databases (Databases): Disposable independent authority.
        tmp_path (Path): Synthetic source repository.
        monkeypatch (pytest.MonkeyPatch): Deterministic elapsed-time injection.
        operation (str): Read-only facade whose result must not escape its deadline.

    Returns:
        None: Every read includes the final authorization call in its elapsed-time budget.
    """
    from witful.native.service import Service

    service, state = prepare(runtime, databases, tmp_path / "source")
    access = runtime.access
    service.publish(access, str(uuid4()), None, state)
    clock = [100.0]
    native = evolve(service.graph.native, monotonic=lambda: clock[0])
    service = evolve(service, graph=evolve(service.graph, native=native))
    original = Service.release

    def delayed_release(self: Service, access: Access, action: str, record: str, registration: Registration, started: float) -> None:
        """
        Advance the synthetic clock after real current-authority verification.

        Args:
            self (Service): Actual configured service.
            access (Access): Original admitted peer.
            action (str): Requested permission.
            record (str): Selected record scope.
            registration (Registration): Expected authority state.
            started (float): Original operation start.

        Returns:
            None: Authorization succeeds but the caller's shorter deadline has elapsed.
        """
        original(self, access, action, record, registration, started)
        clock[0] += 0.002

    monkeypatch.setattr(Service, "release", delayed_release)
    limits = evolve(LIMITS, elapsed_ms=1)
    if operation == "query":
        assert service.query(access, Query("find"), limits).result == "incomplete"
    else:
        with pytest.raises(NativeError, match="incomplete"):
            if operation == "draft":
                service.draft(access, state.inventory, limits)
            else:
                anchor = state.anchors[0]
                service.source(access, anchor.id, anchor.digest, anchor.start, anchor.end, limits)


def test_draft_respects_graph_limits(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Apply declared node limits to drafts as well as persisted discovery queries.

    Args:
        runtime (Runtime): Actual ciphertext backend and synthetic peer.
        databases (Databases): Independent disposable authority.
        tmp_path (Path): Source fixture.

    Returns:
        None: A draft exceeding the requested graph budget fails without publication.
    """
    service, state = prepare(runtime, databases, tmp_path / "source")
    with pytest.raises(NativeError, match="incomplete"):
        service.draft(runtime.access, state.inventory, evolve(LIMITS, nodes=1))
