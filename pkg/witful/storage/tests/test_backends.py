"""
Exercise the same lesson contract against SQLite and a real optional PostgreSQL service.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from witful.lessons import new_lesson
from witful.storage import SQLiteStore, StorageError, open_store
from witful.storage.cli import main

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest import CaptureFixture, FixtureRequest, MonkeyPatch
    from witful.lessons import Lesson
    from witful.storage import LessonStore


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def store(request: FixtureRequest, tmp_path: Path) -> Iterator[LessonStore]:
    """
    Isolate every backend test by file or uniquely named PostgreSQL partition.

    Args:
        request (FixtureRequest): Selected backend.
        tmp_path (Path): Private local database destination.

    Yields:
        LessonStore: Real storage adapter; PostgreSQL is skipped only without its test endpoint.
    """
    endpoint = os.environ.get("WITFUL_TEST_DATABASE_URL") if request.param == "postgres" else None

    if request.param == "postgres" and not endpoint:
        pytest.skip("Set WITFUL_TEST_DATABASE_URL for live PostgreSQL contracts")

    namespace = "test_" + uuid4().hex
    backend = open_store(tmp_path / "lessons.sqlite3", database_url=endpoint, namespace=namespace)
    backend.sync([])

    try:
        yield backend
    finally:
        if endpoint:
            import psycopg

            # Delete only this fixture's random partition, never tables or unrelated records.
            with psycopg.connect(endpoint) as connection:
                connection.execute((Path(__file__).parent / "cleanup.sql").read_text(), {"namespace": namespace})


def records() -> list[Lesson]:
    """
    Create a superseded rule and its sourced correction.

    Returns:
        list[Lesson]: Complete synthetic history in dependency order.
    """
    old = new_lesson("Compiler", "Use deterministic transforms", "Fixture", "2026-01-01T00:00:00Z")
    new = new_lesson("Compiler", "Use explicit deterministic inputs", "Correction", "2026-01-02T00:00:00Z", old.id)
    return [old, new]


def test_search_contract(store: LessonStore) -> None:
    """
    Preserve corrections, duplicate ingestion, bounded queries, and literal query semantics.

    Args:
        store (LessonStore): Selected real backend.

    Returns:
        None: Both engines return the same public observation fields and history membership.
    """
    history = records()
    store.sync(history)
    store.sync(history)
    found = store.search("deterministic")
    assert [row["id"] for row in found] == [history[1].id]
    assert found[0]["source"] == "Correction"
    assert not found[0]["superseded"]
    assert {row["id"] for row in store.search("deterministic", history=True)} == {row.id for row in history}
    assert len(store.search("deterministic", history=True, limit=1)) == 1
    assert store.search("'; DROP TABLE lessons; --") == []
    assert store.search("deterministic") == found

    for query, limit in [("!!!", 10), ("inputs", 0), ("inputs", 101)]:
        with pytest.raises(ValueError):
            store.search(query, limit=limit)


def test_postgres_stale_sync_and_atomic_failure(store: LessonStore) -> None:
    """
    Prove old replicas cannot erase new lessons and invalid batches cannot partially commit.

    Args:
        store (LessonStore): Selected backend; shared semantics apply only to PostgreSQL.

    Returns:
        None: Overlapping concurrent syncs are idempotent and a dangling correction rolls back.
    """
    if isinstance(store, SQLiteStore):
        pytest.skip("Shared replica contract is PostgreSQL-specific")

    history = records()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(store.sync, [history, history[:1], history, history[:1]]))

    store.sync(history[:1])
    assert [row["id"] for row in store.search("deterministic")] == [history[1].id]
    fresh = new_lesson("Rollback", "Transaction sentinel", "Fixture", "2026-01-03T00:00:00Z")

    with pytest.raises(StorageError, match="23503"):
        store.sync([fresh, replace(fresh, id="dangling", supersedes="missing")])

    assert store.search("sentinel") == []


def test_sqlite_defaults_and_invalid_endpoints(tmp_path: Path) -> None:
    """
    Keep the default local and reject malformed endpoints without echoing their contents.

    Args:
        tmp_path (Path): Disposable index location.

    Returns:
        None: Unsupported endpoint values never fall back to SQLite or leak credentials.
    """
    assert isinstance(open_store(tmp_path / "index"), SQLiteStore)

    for endpoint in ["", "https://secret@host", "postgresql:///db", "postgresql://[broken"]:
        with pytest.raises(StorageError) as captured:
            open_store(tmp_path / "index", database_url=endpoint)

        assert "secret" not in str(captured.value)


@pytest.mark.postgres
def test_namespaces_do_not_share_search_results(store: LessonStore, tmp_path: Path) -> None:
    """
    Keep separate identities out of each other's search results in a shared database.

    Args:
        store (LessonStore): Selected backend with a separate, populated partition.
        tmp_path (Path): Unused SQLite fallback destination.

    Returns:
        None: An empty random namespace cannot retrieve another partition's observations.
    """
    endpoint = os.environ.get("WITFUL_TEST_DATABASE_URL")

    if not endpoint or isinstance(store, SQLiteStore):
        pytest.skip("Requires PostgreSQL backend")

    store.sync(records())
    assert store.search("deterministic")

    empty = open_store(tmp_path / "unused", database_url=endpoint, namespace="empty_" + uuid4().hex)
    empty.sync([])
    assert empty.search("deterministic", history=True) == []


def test_offline_check_ignores_remote_credentials(tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    """
    Validate source and SQLite SQL offline even when a broken remote endpoint is configured.

    Args:
        tmp_path (Path): Read-only source stand-in.
        monkeypatch (MonkeyPatch): Isolate database environment selection.
        capsys (CaptureFixture[str]): Captured CLI output.

    Returns:
        None: Check succeeds without a network request or local runtime index.
    """
    (tmp_path / "lessons.jsonl").write_text("")
    monkeypatch.setenv("WITFUL_DATABASE_URL", "invalid-secret")
    assert main(["--repo", str(tmp_path), "check"]) == 0
    assert "invalid-secret" not in capsys.readouterr().out
    assert not (tmp_path / ".lessons.lock").exists()


def test_driver_errors_and_repr_omit_credentials(monkeypatch: MonkeyPatch) -> None:
    """
    Prevent connection failures from exposing the driver's detailed credential-bearing message.

    Args:
        monkeypatch (MonkeyPatch): Replace the network connection with a deterministic failure.

    Returns:
        None: Public errors and adapter representations omit the synthetic secret.
    """
    pytest.importorskip("psycopg")
    import psycopg

    endpoint = "postgresql://user:secret-sentinel@localhost/database"
    backend = open_store(Path("unused"), database_url=endpoint)

    def fail(*args: object, **kwargs: object) -> None:
        """
        Simulate a driver failure with deliberately sensitive details.

        Args:
            *args (object): Positional connection parameters.
            **kwargs (object): Connection options.

        Returns:
            None: Always raises the synthetic connection failure.
        """
        raise psycopg.OperationalError(endpoint)

    monkeypatch.setattr(psycopg, "connect", fail)

    with pytest.raises(StorageError) as captured:
        backend.sync([])

    assert "secret-sentinel" not in str(captured.value)
    assert "secret-sentinel" not in repr(backend)
    assert captured.value.__suppress_context__ is True
