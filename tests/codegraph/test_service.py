"""
Exercise real ciphertext persistence, independent policy checks and atomic graph refreshes.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from threading import Barrier
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import evolve
from witful.codegraph.models import Edge, Graph, Node
from witful.codegraph.service import RepositoryGraph
from witful.codegraph.worker import Extraction
from witful.context.models import Limits
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.api.admission import Admission
from witful.native.api.builder import Builder
from witful.native.domains import Entry, validate
from witful.native.wire import encode_batch

from tests.codegraph.support import repository
from tests.native.requests import body

if TYPE_CHECKING:
    from pathlib import Path

    from witful.codegraph.models import Enrollment
    from witful.codegraph.snapshot import Snapshot

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def extraction(enrollment: Enrollment, snapshot: Snapshot) -> Extraction:
    """
    Supply deterministic static evidence while real storage and authorization run unchanged.

    Args:
        enrollment (Enrollment): Explicit fixture enrollment.
        snapshot (Snapshot): Actual validated Git input.

    Returns:
        Extraction: Small graph with observable provenance.
    """
    assert enrollment.repository and snapshot.sources
    return Extraction(
        (Node("leaf", "leaf", "sample.py", "function", 2, 3), Node("caller", "caller", "sample.py", "function", 5, 6)),
        (Edge("caller", "leaf", "calls", "tree-sitter"),),
        "fixture",
        1,
    )


def test_encrypted_generation_and_policy(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Verify graph separation, tamper resistance inherited from native storage and fresh revocation.

    Args:
        runtime (Runtime): Actual native Git/PostgreSQL service.
        databases (Databases): Independently administered synthetic grant store.
        tmp_path (Path): Disposable repository.

    Returns:
        None: Only the enrolled owner receives current bounded graph evidence.
    """
    enrollment, revision = repository(tmp_path / "source")
    access = runtime.access
    enrollment = evolve(enrollment, tenant=access.scope.tenant, extension=access.scope.identity, subject=access.subject)
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute(
            "UPDATE witful_native_grants SET actions = ARRAY['write','codegraph-build','codegraph-query','rotate','recover'] WHERE id=%s",
            (access.grant,),
        )
    graph = RepositoryGraph(runtime.service, enrollment, extraction)
    operation = str(uuid4())
    receipt = graph.build(access, operation, revision, None)
    assert graph.build(access, operation, revision, None) == receipt
    result = graph.query(access, revision, "leaf", "callers", Limits(tokens=8000, elapsed_ms=30000), 1)
    assert {node.name for node in result.nodes} == {"leaf", "caller"}
    assert "dynamic-calls-may-be-missing" in result.limitations
    graph.rotate(access, str(uuid4()), "resign")
    assert graph.query(access, revision, "leaf", "callers", Limits(tokens=8000, elapsed_ms=30000), 1) == result
    assert graph.recover(access)["generation"] == 2
    for batch in runtime.service.store.history(access.scope):
        encoded = encode_batch(batch, codec.DEFAULT_LIMITS)
        assert b"sample.py" not in encoded and enrollment.repository.encode() not in encoded
        assert enrollment.owner.encode() not in encoded
    # Generic native routes cannot disclose or mutate a reserved graph scope.
    reserved = evolve(runtime.service, graph_scopes=((access.scope.tenant, access.scope.identity),))
    app = Builder(reserved, Admission(1), lambda: True, lambda: access.subject, codegraphs=(enrollment,)).build()
    response = app.test_client().post("/v1/history", data=body(runtime, {"ref": "codegraph"}), content_type="application/cbor")
    assert response.status_code == HTTPStatus.FORBIDDEN
    # Wrong principals, scope substitution and stale publication are denied before releasing graph data.
    for other in (evolve(access, subject="b" * 64), evolve(access, scope=evolve(access.scope, identity=str(uuid4())))):
        with pytest.raises(NativeError):
            graph.query(other, revision, "leaf", "symbol", Limits(), 0)
    with pytest.raises(NativeError):
        graph.build(access, str(uuid4()), revision, None)
    with pytest.raises(NativeError):
        graph.query(access, "0" * 40, "leaf", "symbol", Limits(), 0)
    with pytest.raises(NativeError):
        graph.query(access, revision, "leaf", "symbol", Limits(tokens=1), 0)
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("DELETE FROM witful_native_grants WHERE id=%s", (access.grant,))
    with pytest.raises(NativeError):
        graph.query(access, revision, "leaf", "symbol", Limits(), 0)


def test_concurrent_builds_publish_only_one(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Coordinate competing builders at a barrier and preserve the expected-frontier lease.

    Args:
        runtime (Runtime): Actual native persistence and authority.
        databases (Databases): Independent fixture authority.
        tmp_path (Path): Synthetic source location.

    Returns:
        None: Exactly one complete generation commits; the other reports conflict.
    """
    enrollment, revision = repository(tmp_path / "source")
    access = runtime.access
    enrollment = evolve(enrollment, tenant=access.scope.tenant, extension=access.scope.identity, subject=access.subject)
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute(
            "UPDATE witful_native_grants SET actions=ARRAY['write','codegraph-build','codegraph-query'] WHERE id=%s", (access.grant,)
        )
    barrier = Barrier(2, timeout=20)

    def worker(selected: Enrollment, snapshot: Snapshot) -> Extraction:
        """
        Let both builders reach extraction before either can commit.

        Args:
            selected (Enrollment): Selected owner configuration.
            snapshot (Snapshot): Exact clean source snapshot.

        Returns:
            Extraction: Deterministic graph evidence.
        """
        barrier.wait()
        return extraction(selected, snapshot)

    graph = RepositoryGraph(runtime.service, enrollment, worker)

    def build() -> str:
        """
        Return an observed transaction outcome without suppressing unexpected failures.

        Returns:
            str: Durable or the native failure code.
        """
        try:
            graph.build(access, str(uuid4()), revision, None)
            return "durable"
        except NativeError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: build(), range(2)))
    assert results.count("durable") == 1
    assert runtime.service.store.head(access.scope).generation == 1


@pytest.mark.parametrize("failure", ["source-change", "revocation", "crash"])
def test_interrupted_build_never_publishes(runtime: Runtime, databases: Databases, tmp_path: Path, failure: str) -> None:
    """
    Inject failures after admission but before the final publication boundary.

    Args:
        runtime (Runtime): Real native storage fixture.
        databases (Databases): Independent fixture authority.
        tmp_path (Path): Synthetic source location.
        failure (str): Deterministic interrupted-build condition.

    Returns:
        None: No partial generation or receipt becomes queryable.
    """
    enrollment, revision = repository(tmp_path / "source")
    access = runtime.access
    enrollment = evolve(enrollment, tenant=access.scope.tenant, extension=access.scope.identity, subject=access.subject)
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute(
            "UPDATE witful_native_grants SET actions=ARRAY['write','codegraph-build','codegraph-query'] WHERE id=%s", (access.grant,)
        )

    def worker(selected: Enrollment, snapshot: Snapshot) -> Extraction:
        """
        Change the observed source, revoke the grant or fail before returning SDK output.

        Args:
            selected (Enrollment): Exact enrollment.
            snapshot (Snapshot): Admitted source inputs.

        Returns:
            Extraction: Complete evidence only for the non-crash injected cases.
        """
        if failure == "crash":
            raise NativeError("unavailable")
        if failure == "source-change":
            (tmp_path / "source/sample.py").write_text("changed = True")
        else:
            with psycopg.connect(databases.authority_admin) as admin:
                admin.execute("DELETE FROM witful_native_grants WHERE id=%s", (access.grant,))
        return extraction(selected, snapshot)

    with pytest.raises(NativeError):
        RepositoryGraph(runtime.service, enrollment, worker).build(access, str(uuid4()), revision, None)
    assert runtime.service.store.head(access.scope).generation == 0


def test_graph_domain_does_not_adopt_learning(tmp_path: Path) -> None:
    """
    Keep derived code facts separate from the canonical learning compiler.

    Args:
        tmp_path (Path): Disposable synthetic repository.

    Returns:
        None: A graph is a valid independent native domain with no learned catalog.
    """
    enrollment, revision = repository(tmp_path / "source")
    from witful.codegraph.snapshot import capture

    snapshot = capture(enrollment, revision)
    result = extraction(enrollment, snapshot)
    graph = Graph(enrollment, str(uuid4()), revision, snapshot.tree, snapshot.files, result.nodes, result.edges, result.indexer, 1, False)
    entry = Entry("repository-codegraph", as_data(graph))
    validate((entry,))
    assert codec.decode(codec.encode(entry.value)) == entry.value


def test_sdk_coverage_roundtrip(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Retain SDK coverage through encryption, queries and exact source revalidation.

    Args:
        runtime (Runtime): Real native Git/PostgreSQL persistence.
        databases (Databases): Separately provisioned synthetic authority.
        tmp_path (Path): Disposable source repository.

    Returns:
        None: Omissions remain visible and changed source cannot reuse an authenticated classification.
    """
    enrollment, revision = repository(tmp_path / "source")
    access = runtime.access
    enrollment = evolve(enrollment, profile="sdk", tenant=access.scope.tenant, extension=access.scope.identity, subject=access.subject)
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute(
            "UPDATE witful_native_grants SET actions = ARRAY['write','codegraph-build','codegraph-query'] WHERE id=%s", (access.grant,)
        )

    def worker(selected: Enrollment, snapshot: Snapshot) -> Extraction:
        """
        Return exact source-qualified synthetic classifications while exercising real storage.

        Args:
            selected (Enrollment): Reviewed synthetic enrollment.
            snapshot (Snapshot): Actual current source bytes.

        Returns:
            Extraction: Complete dispositions for all selected text inputs.
        """
        result = extraction(selected, snapshot)
        return evolve(
            result,
            files=tuple(
                evolve(
                    item,
                    coverage="indexed" if item.path == "sample.py" else "unsupported",
                    language="python" if item.path == "sample.py" else "unknown",
                )
                for item in snapshot.files
            ),
        )

    graph = RepositoryGraph(runtime.service, enrollment, worker)
    graph.build(access, str(uuid4()), revision, None)
    result = graph.query(access, revision, "leaf", "callers", Limits(elapsed_ms=30000), 1)
    assert result.languages == ("python",)
    assert {item.status: item.files for item in result.coverage} == {"indexed": 1, "unsupported": 1}
    assert "static-upstream-sdk-languages" in result.limitations
    (tmp_path / "source/README.md").write_text("Changed unsupported text still invalidates the source binding.\n")
    with pytest.raises(NativeError, match="conflict"):
        graph.query(access, revision, "leaf", "callers", Limits(elapsed_ms=30000), 1)
