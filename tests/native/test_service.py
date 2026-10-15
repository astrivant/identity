"""
Exercise real native transactions and authority fencing with independent PostgreSQL roles and synthetic keys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import evolve, frozen
from witful.exceptions import NativeError
from witful.native.domains import Entry
from witful.native.storage import Head, Scope

if TYPE_CHECKING:
    from witful.native.storage import Batch, Object, Store

    from tests.native.conftest import Fixture
    from tests.native.database import Databases


from tests.native.runtime import Runtime, lesson


def test_atomic_history_retry_and_search(runtime: Runtime) -> None:
    """
    Preserve one logical operation, exact receipt and complete branch state across retries.

    Args:
        runtime (Runtime): Real service fixture.

    Returns:
        None: Assertions establish service parity across the supported backends.
    """
    service, access = runtime.service, runtime.access
    operation = str(uuid4())
    first = service.append(access, operation, "main", None, (lesson(),), b"exact original bytes\n")
    assert first.generation == 1
    assert service.append(access, operation, "main", None, (lesson(),), b"exact original bytes\n") == first
    history = service.history(access, "main")
    assert len(history) == 1
    revision, entry = history[0]
    assert entry == lesson()
    assert service.read(access, revision.id) == entry
    assert service.search(access, "main", "canary") == (revision.id,)
    assert service.search(access, "main", "absent") == ()
    assert revision.source is not None
    assert service.open(access, revision.source) == b"exact original bytes\n"
    service.branch(access, str(uuid4()), "review", revision.id)
    assert service.history(access, "review") == history
    with pytest.raises(NativeError, match="conflict"):
        service.append(access, operation, "main", None, (lesson("changed"),))
    with pytest.raises(NativeError, match="conflict"):
        service.append(access, str(uuid4()), "main", None, (lesson("stale"),))
    assert service.store.head(access.scope).generation == 2
    batches = service.store.history(access.scope)
    assert len(batches) == 2
    assert all(b"synthetic-native-canary" not in item.payload for batch in batches for item in (batch.root, batch.receipt, *batch.objects))


def test_scope_revocation_and_stale_epoch(runtime: Runtime, databases: Databases, fixture: Fixture) -> None:
    """
    Deny unauthorized or stale requests before releasing keys or returning cached state.

    Args:
        runtime (Runtime): Real service fixture.
        databases (Databases): Independent control-plane administration.
        fixture (Fixture): Observable synthetic key calls.

    Returns:
        None: Wrong tenant, task, certificate, epoch and revoked grants fail closed.
    """
    service, access = runtime.service, runtime.access
    for invalid in (
        evolve(access, scope=Scope(str(uuid4()), access.scope.identity)),
        evolve(access, task=str(uuid4())),
        evolve(access, subject="b" * 64),
        evolve(access, epoch=2),
    ):
        with pytest.raises(NativeError):
            service.append(invalid, str(uuid4()), "main", None, (lesson(),))
    assert fixture.keys.calls == []
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("UPDATE witful_native_grants SET enabled = false WHERE id = %s", (access.grant,))
    with pytest.raises(NativeError, match="denied"):
        service.append(access, str(uuid4()), "main", None, (lesson(),))
    assert service.store.head(access.scope) == Head()


def test_rollback_detection_and_domain_rejection(runtime: Runtime, databases: Databases) -> None:
    """
    Keep malformed legacy records and independently stale database frontiers from adoption.

    Args:
        runtime (Runtime): Real service fixture.
        databases (Databases): Independent control-plane administration.

    Returns:
        None: Neither invalid domain data nor backend-only history changes become authoritative.
    """
    service, access = runtime.service, runtime.access
    with pytest.raises(NativeError):
        service.append(access, str(uuid4()), "main", None, (Entry("lesson", {"id": "invalid"}),))
    assert service.store.head(access.scope) == Head()
    service.append(access, str(uuid4()), "main", None, (lesson(),))
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute(
            "UPDATE witful_native_registry SET generation = 0, root = NULL, digest = ''::bytea WHERE tenant = %s AND identity_id = %s",
            (access.scope.tenant, access.scope.identity),
        )
    with pytest.raises(NativeError, match="conflict"):
        service.history(access, "main")


@frozen
class LostAcknowledgment:
    """
    Interrupt after a real committed data transaction to exercise the control-plane recovery boundary.

    Attributes:
        store (Store): Actual backend, not a simulated transaction implementation.
    """

    store: Store

    def commit(self, scope: Scope, batch: Batch) -> Head:
        """
        Commit then simulate a lost acknowledgment.

        Args:
            scope (Scope): Authorized test partition.
            batch (Batch): Actual prepared ciphertext.

        Returns:
            Head: Never returns because the acknowledgment is deliberately lost.
        """
        self.store.commit(scope, batch)
        raise NativeError("unknown")

    def head(self, scope: Scope) -> Head:
        """
        Delegate frontier readback.

        Args:
            scope (Scope): Test partition.

        Returns:
            Head: Real durable frontier.
        """
        return self.store.head(scope)

    def get(self, scope: Scope, identifiers: tuple[str, ...]) -> tuple[Object, ...]:
        """
        Delegate ciphertext retrieval.

        Args:
            scope (Scope): Test partition.
            identifiers (tuple[str, ...]): Exact IDs.

        Returns:
            tuple[Object, ...]: Real stored ciphertext.
        """
        return self.store.get(scope, identifiers)

    def receipt(self, scope: Scope, operation: str) -> Object | None:
        """
        Delegate exact receipt lookup.

        Args:
            scope (Scope): Test partition.
            operation (str): Stable operation UUID.

        Returns:
            Object | None: Actual committed receipt.
        """
        return self.store.receipt(scope, operation)

    def history(self, scope: Scope) -> tuple[Batch, ...]:
        """
        Delegate complete ciphertext recovery history.

        Args:
            scope (Scope): Test partition.

        Returns:
            tuple[Batch, ...]: Real retained transactions.
        """
        return self.store.history(scope)


def test_unknown_commit_recovers_exact_receipt(runtime: Runtime) -> None:
    """
    Reconcile the precise prepared bytes after a committed write loses its acknowledgment.

    Args:
        runtime (Runtime): Real service fixture.

    Returns:
        None: Recovery neither duplicates the semantic operation nor leaves a falsely successful receipt.
    """
    service, access = runtime.service, runtime.access
    operation = str(uuid4())
    interrupted = evolve(service, store=LostAcknowledgment(service.store))
    with pytest.raises(NativeError, match="unknown"):
        interrupted.append(access, operation, "main", None, (lesson(),))
    with pytest.raises(NativeError, match="unknown"):
        service.history(access, "main")
    assert service.store.head(access.scope).generation == 1
    assert service.authority.recover(access, service.store, int(service.clock())).generation == 1
    receipt = service.append(access, operation, "main", None, (lesson(),))
    assert receipt.generation == 1
    assert len(service.store.history(access.scope)) == 1
