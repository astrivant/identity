"""
Exercise independently authorized disclosure, atomic child visibility and exact retries against both real storage adapters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import evolve
from witful.exceptions import NativeError
from witful.native.backup import Archive, verify
from witful.native.derivation import derive
from witful.native.derivation_models import ChildEvidence, Decision
from witful.native.kinds import DERIVATION
from witful.native.models import parse

from tests.native.derivation import children

if TYPE_CHECKING:
    from witful.native.git import Git
    from witful.native.postgres import Postgres
    from witful.native.storage import Batch, Head, Scope

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_scoped_split_omits_unselected_history_and_original_source(runtime: Runtime, databases: Databases) -> None:
    """
    Publish two independently scoped children while preserving omissions only in the parent's encrypted decision.

    Args:
        runtime (Runtime): Real Git or PostgreSQL parent.
        databases (Databases): Synthetic independent scope/grant provisioning.

    Returns:
        None: Children cannot traverse source or siblings, retain no whole-source bytes and have explicit honest adoption provenance.
    """
    expected, outputs = children(runtime, databases)
    original = runtime.service.history(runtime.access, "main")
    operation = str(uuid4())
    receipt = derive(runtime.service, runtime.access, operation, expected, outputs, "Reviewed synthetic subset disclosure")
    assert derive(runtime.service, runtime.access, operation, expected, outputs, "Reviewed synthetic subset disclosure") == receipt
    assert runtime.service.history(runtime.access, "main") == original
    _, parent = runtime.service.snapshot(runtime.access, "export", "*")
    pointer = next(item for item in parent.archives if item.kind == DERIVATION)
    decision = parse(runtime.service.open(runtime.access, pointer), Decision)
    assert decision.mode == "split" and decision.omitted == (original[-1][0].id,)
    for child in outputs:
        history = child.service.history(child.access, child.ref)
        assert len(history) == 1 and history[0][1] == child.selections[0].entry
        assert history[0][0].parents == () and history[0][0].source is None
        with pytest.raises(NativeError, match="denied"):
            child.service.read(child.access, original[0][0].id)
        _, frontier = child.service.snapshot(child.access, "export", "*")
        evidence = parse(child.service.open(child.access, frontier.archives[0]), ChildEvidence)
        assert evidence.source.record == expected
        assert evidence.adopted[0].sources == child.selections[0].sources
        assert original[-1][0].id not in str(evidence)
        verify(child.service, child.access, Archive(child.access.scope, child.service.store.history(child.access.scope)))
    with pytest.raises(NativeError, match="conflict"):
        derive(runtime.service, runtime.access, operation, expected, outputs, "Changed review input")


def test_partial_copy_remains_invisible_and_resumes_exact_bytes(
    runtime: Runtime,
    databases: Databases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Lose the response after a real child commit and recover the exact prepared group without exposing a partial split.

    Args:
        runtime (Runtime): Real source and child data backend.
        databases (Databases): Independent synthetic authorization.
        monkeypatch (pytest.MonkeyPatch): Deterministic failure after the actual last child commit.

    Returns:
        None: Every scope remains fenced until all exact bytes are independently read back and atomically acknowledged.
    """
    expected, outputs = children(runtime, databases)
    operation = str(uuid4())
    store_type = type(runtime.service.store)
    original = store_type.commit
    committed: list[Batch] = []

    def fail(store: Git | Postgres, scope: Scope, batch: Batch) -> Head:
        """
        Commit the real bytes, then simulate a lost acknowledgment for one child.

        Args:
            store (Git | Postgres): Actual adapter instance.
            scope (Scope): Explicit destination identity.
            batch (Batch): Exact prepared transaction.

        Returns:
            Head: Actual result except at the injected uncertain boundary.
        """
        result = original(store, scope, batch)
        committed.append(batch)
        if scope == outputs[-1].access.scope:
            raise NativeError("unknown")
        return result

    monkeypatch.setattr(store_type, "commit", fail)
    with pytest.raises(NativeError, match="unknown"):
        derive(runtime.service, runtime.access, operation, expected, outputs, "Explicit subset")
    for service, access in ((runtime.service, runtime.access), *((child.service, child.access) for child in outputs)):
        with pytest.raises(NativeError, match="unknown"):
            service.history(access, "main")
    with psycopg.connect(databases.authority_admin) as admin:
        rows = admin.execute(
            "SELECT generation, transition FROM witful_native_registry WHERE tenant=%s ORDER BY identity_id", (runtime.access.scope.tenant,)
        ).fetchall()
        assert sorted(row[0] for row in rows) == [0, 0, 1]
        assert len({bytes(row[1]) for row in rows}) == 1
        assert b"private-canary" not in bytes(rows[0][1])
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("UPDATE witful_native_grants SET enabled=false WHERE id=%s", (outputs[-1].access.grant,))
    with pytest.raises(NativeError, match="denied"):
        derive(runtime.service, runtime.access, operation, expected, outputs, "Explicit subset")
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("UPDATE witful_native_grants SET enabled=true WHERE id=%s", (outputs[-1].access.grant,))
    monkeypatch.setattr(store_type, "commit", original)
    receipt = derive(runtime.service, runtime.access, operation, expected, outputs, "Explicit subset")
    assert receipt.operation == operation
    for (service, access), batch in zip(
        ((runtime.service, runtime.access), *((child.service, child.access) for child in outputs)),
        committed,
        strict=True,
    ):
        assert service.store.history(access.scope)[-1] == batch
        assert service.authority.check(access, "read", "*", int(service.clock())).head == batch.target


def test_destination_grants_do_not_follow_parent_authority(runtime: Runtime, databases: Databases) -> None:
    """
    Require each independently administered import grant before preparing any copy.

    Args:
        runtime (Runtime): Fully authorized synthetic parent.
        databases (Databases): Test authority administrator revoking one child import permission.

    Returns:
        None: Source review cannot create recipient permissions or accept a substituted actor or scope.
    """
    expected, outputs = children(runtime, databases)
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("UPDATE witful_native_grants SET actions=array_remove(actions, 'import') WHERE id=%s", (outputs[-1].access.grant,))
    with pytest.raises(NativeError, match="denied"):
        derive(runtime.service, runtime.access, str(uuid4()), expected, outputs, "Approved source only")
    assert all(child.service.store.head(child.access.scope).generation == 0 for child in outputs)
    with pytest.raises(NativeError, match="denied"):
        derive(
            runtime.service,
            runtime.access,
            str(uuid4()),
            expected,
            (evolve(outputs[0], access=evolve(outputs[0].access, subject="b" * 64)),),
            "Substituted actor",
        )
    with pytest.raises(NativeError, match="invalid"):
        derive(runtime.service, runtime.access, str(uuid4()), expected, (outputs[0], outputs[0]), "Duplicate scope")


def test_failed_publication_rolls_back_every_acknowledgment(runtime: Runtime, databases: Databases) -> None:
    """
    Fail the last child registry update after earlier updates and prove the whole publication transaction rolls back.

    Args:
        runtime (Runtime): Actual data backend with independently transactional authority.
        databases (Databases): Disposable administrator used only to install a deterministic failure trigger.

    Returns:
        None: No mixed published frontier survives failure; a retry uses the retained preparation and publishes every child.
    """
    from pathlib import Path

    from psycopg import sql

    expected, outputs = children(runtime, databases)
    operation = str(uuid4())
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute((Path(__file__).parent / "resources/derivation-publication-failure.sql").read_text())
        admin.execute(
            sql.SQL(
                "CREATE TRIGGER synthetic_derivation_failure BEFORE UPDATE ON witful_native_registry "
                "FOR EACH ROW EXECUTE FUNCTION witful_native_fail_derivation({})"
            ).format(sql.Literal(outputs[-1].access.scope.identity))
        )
    try:
        with pytest.raises(NativeError, match="unknown"):
            derive(runtime.service, runtime.access, operation, expected, outputs, "Atomic reviewed subset")
        with psycopg.connect(databases.authority_admin) as admin:
            rows = admin.execute(
                "SELECT generation, transition FROM witful_native_registry WHERE tenant=%s",
                (runtime.access.scope.tenant,),
            ).fetchall()
            assert sorted(row[0] for row in rows) == [0, 0, 1]
            assert all(row[1] is not None for row in rows)
        # Every data transaction did commit; only the final authority transaction failed.
        assert all(child.service.store.head(child.access.scope).generation == 1 for child in outputs)
    finally:
        with psycopg.connect(databases.authority_admin) as admin:
            admin.execute("DROP TRIGGER synthetic_derivation_failure ON witful_native_registry")
            admin.execute("DROP FUNCTION witful_native_fail_derivation()")
    receipt = derive(runtime.service, runtime.access, operation, expected, outputs, "Atomic reviewed subset")
    assert receipt.operation == operation
    with psycopg.connect(databases.authority_admin) as admin:
        rows = admin.execute(
            "SELECT generation, transition FROM witful_native_registry WHERE tenant=%s", (runtime.access.scope.tenant,)
        ).fetchall()
        assert sorted(row[0] for row in rows) == [1, 1, 2]
        assert all(row[1] is None for row in rows)


def test_fork_api_uses_configured_target_and_rejects_mode_mismatch(runtime: Runtime, databases: Databases) -> None:
    """
    Publish through the real consolidated endpoint with a configured recipient and an explicit single-child review.

    Args:
        runtime (Runtime): Parent source and TLS subject stand-in.
        databases (Databases): Explicit synthetic target provisioning.

    Returns:
        None: An unknown alias or inconsistent requested operation cannot create a child.
    """
    from http import HTTPStatus

    from witful.native import domains
    from witful.native.api.admission import Admission
    from witful.native.api.builder import Builder
    from witful.native.config import DerivationTarget

    from tests.native.requests import body

    expected, outputs = children(runtime, databases)
    child = outputs[0]
    target = DerivationTarget(
        "recipient",
        child.service.authority.backend,
        child.access.scope.tenant,
        child.access.scope.identity,
        child.access.grant,
        child.access.task,
        child.access.epoch,
        child.access.policy,
    )
    client = (
        Builder(runtime.service, Admission(1), lambda: True, lambda: runtime.access.subject, derivations=(target,)).build().test_client()
    )
    request = {
        "operation": str(uuid4()),
        "expected": expected,
        "mode": "split",
        "reason": "Reviewed single child",
        "children": [
            {
                "destination": "recipient",
                "ref": child.ref,
                "selections": [
                    {"sources": list(selection.sources), "entry": domains.encode(selection.entry)} for selection in child.selections
                ],
            }
        ],
    }
    assert client.post("/v1/derive", data=body(runtime, request), content_type="application/cbor").status_code == HTTPStatus.BAD_REQUEST
    request["mode"] = "fork"
    response = client.post("/v1/derive", data=body(runtime, request), content_type="application/cbor")
    assert response.status_code == HTTPStatus.OK
    assert child.service.history(child.access, "main")[0][1] == child.selections[0].entry
    assert response.headers["Cache-Control"] == "no-store"


def test_split_retains_projection_permissions_after_lost_ack(
    runtime: Runtime, databases: Databases, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Enqueue each independently scoped split and keep its export requirement after a restart disables scheduling.

    Args:
        runtime (Runtime): Actual parent data adapter.
        databases (Databases): Independent test authority administrator.
        monkeypatch (pytest.MonkeyPatch): Lost acknowledgment after a real child commit.

    Returns:
        None: Recovery denies revoked projection and later reuses the exact outbox candidates in every scope.
    """
    from witful.native.projection.models import Policy
    from witful.native.projection.status import completion, status

    from tests.native.projection import configured
    from tests.native.runtime import Runtime as FixtureRuntime

    expected, outputs = children(runtime, databases)
    source = configured(runtime, databases)
    outputs = tuple(evolve(child, service=configured(FixtureRuntime(child.service, child.access), databases)) for child in outputs)
    operation = str(uuid4())
    original = type(source.store).commit

    def lost(store: Git | Postgres, scope: Scope, batch: Batch) -> Head:
        """
        Lose the final child acknowledgment without discarding committed data.

        Args:
            store (Git | Postgres): Actual storage adapter.
            scope (Scope): Independently scoped destination.
            batch (Batch): Retained prepared transaction.

        Returns:
            Head: Committed frontier except at the injected unknown boundary.
        """
        result = original(store, scope, batch)
        if scope == outputs[-1].access.scope:
            raise NativeError("unknown")
        return result

    monkeypatch.setattr(type(source.store), "commit", lost)
    with pytest.raises(NativeError, match="unknown"):
        derive(source, runtime.access, operation, expected, outputs, "Reviewed projected split")
    saved = tuple(
        service.store.history(access.scope)[-1]
        for service, access in ((source, runtime.access), *((child.service, child.access) for child in outputs))
    )
    source = evolve(source, projection=Policy())
    outputs = tuple(evolve(child, service=evolve(child.service, projection=Policy())) for child in outputs)
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("UPDATE witful_native_grants SET actions=array_remove(actions, 'project') WHERE id=%s", (outputs[-1].access.grant,))
    monkeypatch.setattr(type(source.store), "commit", original)
    with pytest.raises(NativeError, match="denied"):
        derive(source, runtime.access, operation, expected, outputs, "Reviewed projected split")
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("UPDATE witful_native_grants SET actions=array_append(actions, 'project') WHERE id=%s", (outputs[-1].access.grant,))
    receipt = derive(source, runtime.access, operation, expected, outputs, "Reviewed projected split")
    assert receipt.remote_required
    for (service, access), batch in zip(
        ((source, runtime.access), *((child.service, child.access) for child in outputs)), saved, strict=True
    ):
        assert service.store.history(access.scope)[-1] == batch
        assert status(service, access)["queue_size"] == 1
        assert not completion(service, access, operation)["complete"]
