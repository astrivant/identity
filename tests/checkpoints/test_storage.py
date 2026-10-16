"""
Run the same transactional checkpoint contract against SQLite and optional PostgreSQL.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from attrs import evolve
from witful.checkpoints.journal import checkpoint_id, record
from witful.checkpoints.storage import SQLiteCheckpointStore

if TYPE_CHECKING:
    from collections.abc import Iterator

    from witful.checkpoints.storage import CheckpointStore


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[CheckpointStore]:
    """
    Isolate each backend contract in a temporary file or random PostgreSQL partition.

    Args:
        request (pytest.FixtureRequest): Selected backend parameter.
        tmp_path (Path): SQLite scratch directory.

    Yields:
        CheckpointStore: Empty isolated mirror, removed after the test.
    """
    if request.param == "sqlite":
        yield SQLiteCheckpointStore(tmp_path / "checkpoints.sqlite3")
        return

    endpoint = os.environ.get("WITFUL_TEST_DATABASE_URL")

    if not endpoint:
        pytest.skip("Set WITFUL_TEST_DATABASE_URL to run PostgreSQL checkpoint contracts")

    from witful.checkpoints.postgres import PostgreSQLCheckpointStore
    from witful.storage.connection import connect

    namespace = "checkpoint_test_" + uuid4().hex

    try:
        yield PostgreSQLCheckpointStore(endpoint, namespace)
    finally:
        with connect(endpoint) as connection:
            connection.execute((Path(__file__).parent / "cleanup.sql").read_text(), {"namespace": namespace})


def test_concurrent_seed_retry_prefix_and_conflict(collection: Path, store: CheckpointStore) -> None:
    """
    Serialize compatible concurrent writers and fail divergent imports before mutation.

    Args:
        collection (Path): Synthetic source collection.
        store (CheckpointStore): Isolated backend under test.

    Returns:
        None: Both engines preserve exactly one ordered history under retries and conflicts.
    """
    first = record(collection, collection, "example/one")
    second = record(collection, collection, "example/two")
    events = (first, second)

    with ThreadPoolExecutor(max_workers=3) as pool:
        added = list(pool.map(store.seed, [events] * 3))

    assert sum(added) == 2
    assert store.seed([first]) == 0
    assert store.load() == events
    divergent = evolve(second, project="example/other")
    divergent = evolve(divergent, id=checkpoint_id(divergent))

    with pytest.raises(ValueError, match="diverge"):
        store.seed([first, divergent])

    assert store.load() == events


def test_namespace_separation(collection: Path, tmp_path: Path) -> None:
    """
    Share one SQLite database without mixing independent collection histories.

    Args:
        collection (Path): Synthetic evidence source.
        tmp_path (Path): Isolated database directory.

    Returns:
        None: Reading another namespace does not reveal the first collection's checkpoints.
    """
    event = record(collection, collection, "example/one")
    path = tmp_path / "shared.sqlite3"
    one = SQLiteCheckpointStore(path, "one")
    two = SQLiteCheckpointStore(path, "two")
    assert one.seed([event]) == 1
    assert two.load() == ()
    assert two.seed([event]) == 1
    assert one.load() == two.load() == (event,)
    assert path.stat().st_mode & 0o777 == 0o600
