"""
Prove that recovery waits for backend writers instead of mistaking an old visible snapshot for an aborted commit.
"""

from __future__ import annotations

import selectors
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from witful.native.git import Git
from witful.native.postgres import Postgres, sql

from tests.native.runtime import lesson

if TYPE_CHECKING:
    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_postgres_recovery_waits_for_inflight_commit(runtime: Runtime, databases: Databases) -> None:
    """
    Observe a real blocked row-lock reader and then verify it sees the committed successor rather than the old MVCC snapshot.

    Args:
        runtime (Runtime): Real native service.
        databases (Databases): Synthetic PostgreSQL administration for lock-state observations.

    Returns:
        None: Recovery settlement waits behind the actual writer's transaction.
    """
    service, access = runtime.service, runtime.access
    store = service.store
    if not isinstance(store, Postgres):
        pytest.skip("PostgreSQL-specific MVCC settlement contract")
    operation = str(uuid4())
    service.append(access, operation, "main", None, (lesson(),))
    head = store.head(access.scope)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.transaction(access.scope) as writer:
            writer.execute(sql("locked-head"), (access.scope.tenant, access.scope.identity))
            writer.execute(sql("advance"), (2, head.root, head.digest, access.scope.tenant, access.scope.identity))
            # A normal read deliberately demonstrates the stale observation that recovery must not use.
            assert store.head(access.scope).generation == 1
            pending = pool.submit(store.resolve, access.scope, operation)
            blocked = False
            deadline = time.monotonic() + 5
            with psycopg.connect(databases.data_admin, autocommit=True) as observer:
                while time.monotonic() < deadline:
                    row = observer.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock' AND query LIKE '%witful_native_heads%'"
                    ).fetchone()
                    if row is not None and row[0] > 0:
                        blocked = True
                        break
                    Event().wait(0.01)
            assert blocked
            assert not pending.done()
        settled, receipt = pending.result(timeout=5)
    assert settled.generation == 2
    assert receipt == store.receipt(access.scope, operation)


def test_git_ref_child_retains_lock_after_parent_closes(runtime: Runtime) -> None:
    """
    Keep recovery blocked while an actual Git child retains the descriptor after the parent owner releases its copy.

    Args:
        runtime (Runtime): Real local Git store fixture.

    Returns:
        None: The child-held fence survives parent descriptor closure and releases only after Git exits.
    """
    store, access = runtime.service.store, runtime.access
    if not isinstance(store, Git):
        pytest.skip("Git-specific inherited descriptor contract")
    operation = str(uuid4())
    runtime.service.append(access, operation, "main", None, (lesson(),))
    with store.lock(access.scope) as descriptor:
        child = subprocess.Popen(
            ["git", "update-ref", "--stdin"],
            cwd=store.directory,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            pass_fds=(descriptor,),
        )
    try:
        assert child.stdin is not None and child.stdout is not None
        child.stdin.write(b"start\n")
        child.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            assert selector.select(5), "Git did not acknowledge the controlled transaction"
        assert child.stdout.readline() == b"start: ok\n"
        # A second file description cannot acquire the inherited lock after the parent's context has exited.
        import fcntl
        import os

        descriptor = os.open(store.directory / f"native-{access.scope.tenant}-{access.scope.identity}.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        child.stdin.close()
        assert child.wait(timeout=5) == 0
        assert store.resolve(access.scope, operation)[0].generation == 1
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        if child.stdout is not None:
            child.stdout.close()
        if child.stdin is not None and not child.stdin.closed:
            child.stdin.close()
