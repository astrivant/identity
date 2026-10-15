"""
Verify real cross-backend cutover, reverse catch-up and interrupted acknowledgment recovery with synthetic history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from attrs import evolve
from witful.exceptions import NativeError
from witful.native import migration
from witful.native.git import Git, git
from witful.native.migration import abort, migrate
from witful.native.postgres import Postgres

from tests.native.runtime import lesson

if TYPE_CHECKING:
    from pathlib import Path

    from witful.native.authority import Access, Registration
    from witful.native.service import Service
    from witful.native.storage import Batch, Head, Scope, Store

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


@pytest.fixture
def destination(runtime: Runtime, databases: Databases, tmp_path: Path) -> Service:
    """
    Select the other real backend without changing the registry's current authority.

    Args:
        runtime (Runtime): Current source service.
        databases (Databases): Disposable PostgreSQL storage.
        tmp_path (Path): Synthetic Git destination.

    Returns:
        Service: Protected test destination with a different backend UUID and the same authority.
    """
    store: Store
    if isinstance(runtime.service.store, Git):
        store = Postgres(databases.data)
    else:
        directory = tmp_path / "destination.git"
        directory.mkdir()
        git(directory, ("init", "--bare", "."))
        store = Git(directory, "Synthetic Contract", "contract@example.invalid")
    return evolve(runtime.service, store=store, authority=evolve(runtime.service.authority, backend=str(uuid4())))


def test_cutover_and_reverse_migration_preserve_new_writes(runtime: Runtime, destination: Service) -> None:
    """
    Retain exact source batches, fence stale writers and carry all new destination writes back on rollback.

    Args:
        runtime (Runtime): Original authoritative service.
        destination (Service): Opposite backend with separate identity.

    Returns:
        None: Both directions preserve acknowledged history and advance the routing epoch rather than flipping configuration.
    """
    source, access = runtime.service, runtime.access
    source.append(access, str(uuid4()), "main", None, (lesson("original"),), b"exact original")
    original = source.store.history(access.scope)
    operation = str(uuid4())
    receipt = migrate(source, destination, access, operation)
    assert receipt.epoch == 2
    assert destination.store.history(access.scope)[: len(original)] == original
    assert migrate(source, destination, access, operation) == receipt
    with pytest.raises(NativeError, match="conflict"):
        source.history(access, "main")
    migrated = evolve(access, epoch=2)
    records = destination.history(migrated, "main")
    destination.append(migrated, str(uuid4()), "main", records[-1][0].id, (lesson("new destination write"),))
    before_reverse = destination.store.history(access.scope)
    reverse = migrate(destination, source, migrated, str(uuid4()))
    assert reverse.epoch == 3
    assert source.store.history(access.scope)[: len(before_reverse)] == before_reverse
    assert [entry for _, entry in source.history(evolve(access, epoch=3), "main")] == [lesson("original"), lesson("new destination write")]
    with pytest.raises(NativeError, match="conflict"):
        destination.history(migrated, "main")


def test_lost_cutover_ack_resumes_exact_candidate(runtime: Runtime, destination: Service, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Kill the acknowledgment path after the actual destination commit and retry the unchanged durable preparation.

    Args:
        runtime (Runtime): Real source and independent control database.
        destination (Service): Real destination.
        monkeypatch (pytest.MonkeyPatch): Deterministic fault at the post-commit boundary.

    Returns:
        None: Source stays frozen and recovery neither duplicates the migration nor invents a new candidate.
    """
    source, access = runtime.service, runtime.access
    source.append(access, str(uuid4()), "main", None, (lesson(),))
    operation = str(uuid4())
    original = type(destination.store).commit
    interrupted = False

    def lose_ack(store: Store, scope: Scope, batch: Batch) -> Head:
        """
        Commit real bytes before injecting one lost acknowledgment for the cutover operation.

        Args:
            store (Store): Actual destination.
            scope (Scope): Original scope.
            batch (Batch): Exact durable preparation.

        Returns:
            Head: Real committed result except on the injected unknown outcome.
        """
        nonlocal interrupted
        result = original(store, scope, batch)
        if batch.operation == operation and not interrupted:
            interrupted = True
            raise NativeError("unknown")
        return result

    monkeypatch.setattr(type(destination.store), "commit", lose_ack)
    with pytest.raises(NativeError, match="unknown"):
        migrate(source, destination, access, operation)
    committed = destination.store.head(access.scope)
    with pytest.raises(NativeError, match="unknown"):
        source.history(access, "main")
    with pytest.raises(NativeError, match="conflict"):
        abort(source, access, operation)
    receipt = migrate(source, destination, access, operation)
    assert receipt.generation == committed.generation
    assert destination.store.head(access.scope) == committed
    assert len(destination.history(evolve(access, epoch=2), "main")) == 1


def test_abort_before_candidate_preserves_source(runtime: Runtime, destination: Service, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Stop before preparing cutover and explicitly unfreeze without deleting the retained partial destination.

    Args:
        runtime (Runtime): Original authoritative service.
        destination (Service): Inactive backfill recipient.
        monkeypatch (pytest.MonkeyPatch): Deterministic pre-candidate fault.

    Returns:
        None: Source remains unchanged and ordinary reads resume only after explicit migration cancellation.
    """
    source, access = runtime.service, runtime.access
    source.append(access, str(uuid4()), "main", None, (lesson(),))
    operation = str(uuid4())

    def fail_before_prepare(
        source: Service, access: Access, transition: migration.Transition, registration: Registration, request: str
    ) -> Batch:
        """
        Simulate unavailable key custody before any cutover batch can become durable.

        Args:
            source (Service): Current source.
            access (Access): Migration grant.
            transition (migration.Transition): Durable backup and freeze.
            registration (Registration): Frozen current state.
            request (str): Exact semantic request.

        Returns:
            Batch: Never returned at this injected failure boundary.
        """
        raise NativeError("unavailable")

    monkeypatch.setattr(migration, "cutover_candidate", fail_before_prepare)
    with pytest.raises(NativeError, match="unavailable"):
        migrate(source, destination, access, operation)
    assert destination.store.history(access.scope) == source.store.history(access.scope)
    abort(source, access, operation)
    assert len(source.history(access, "main")) == 1
