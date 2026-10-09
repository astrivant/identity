"""
Exercise complete decision archive seeding and retrieval against a disposable PostgreSQL database.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from attrs import evolve
from sapience.life.journal import read_archive, record_decision
from sapience.life.replay import prefix, render

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sapience.life.models import Decision
    from sapience.life.postgres import PostgreSQLLifeStore


@pytest.fixture
def remote() -> Iterator[PostgreSQLLifeStore]:
    """
    Isolate each remote test in a random partition and remove only its fixture records.

    Yields:
        PostgreSQLLifeStore: Live store when SAPIENCE_TEST_DATABASE_URL is supplied.
    """
    endpoint = os.environ.get("SAPIENCE_TEST_DATABASE_URL")

    if not endpoint:
        pytest.skip("Set SAPIENCE_TEST_DATABASE_URL for PostgreSQL audit contracts")

    from sapience.life.postgres import PostgreSQLLifeStore
    from sapience.storage.connection import connect

    namespace = "life_test_" + uuid4().hex
    store = PostgreSQLLifeStore(endpoint, namespace)

    try:
        yield store
    finally:
        with connect(endpoint) as connection:
            for filename in ("cleanup-events.sql", "cleanup-snapshots.sql"):
                connection.execute((Path(__file__).parent / filename).read_text(), {"namespace": namespace})


@pytest.mark.postgres
def test_seed_retries_prefixes_conflicts_and_database_replay(source: Path, decision: Decision, remote: PostgreSQLLifeStore) -> None:
    """
    Preserve history during concurrent seeding and reproduce views directly from the database archive.

    Args:
        source (Path): Synthetic source checkout.
        decision (Decision): Initial reviewed choice.
        remote (PostgreSQLLifeStore): Empty isolated PostgreSQL partition.

    Returns:
        None: Imports are atomic and idempotent; database replay matches file replay exactly.
    """
    first = record_decision(source, decision)
    record_decision(source, evolve(decision, supersedes=first.id, choice="Append with snapshots"))
    archive = read_archive(source)

    with ThreadPoolExecutor(max_workers=3) as pool:
        counts = list(pool.map(remote.seed, (archive, archive, archive)))

    assert sum(counts) == 2
    assert remote.seed(prefix(archive, first.id)) == 0
    assert remote.load() == archive
    local = source / "local-replay"
    stored = source / "database-replay"
    outputs = render(archive, source, local, historical=True)
    render(remote.load(), source, stored, historical=True)
    assert all(path.read_bytes() == (stored / path.name).read_bytes() for path in outputs)

    # A complete valid competing branch must fail before altering either events or snapshots remotely.
    from sapience.life.contracts import content_id
    from sapience.life.models import Archive

    divergent = evolve(first, decision=evolve(decision, choice="Replace state"))
    divergent = evolve(divergent, id=content_id(divergent))

    with pytest.raises(ValueError, match="diverge"):
        remote.seed(Archive((divergent,), archive.snapshots))

    assert remote.load() == archive


@pytest.mark.postgres
def test_corrupted_remote_archive_blocks_seeding(source: Path, decision: Decision, remote: PostgreSQLLifeStore) -> None:
    """
    Detect altered stored payloads before an idempotent seed can mistakenly report success.

    Args:
        source (Path): Synthetic input source.
        decision (Decision): Initial reviewed choice.
        remote (PostgreSQLLifeStore): Disposable remote namespace.

    Returns:
        None: A corrupted snapshot prevents both loading and extending the remote archive.
    """
    from sapience.knowledge.contracts import as_data
    from sapience.life.contracts import canonical
    from sapience.storage.connection import connect

    record_decision(source, decision)
    archive = read_archive(source)
    remote.seed(archive)
    corrupted = evolve(archive.snapshots[0], lessons_jsonl="")

    with connect(remote.database_url) as connection:
        connection.execute(
            (Path(__file__).parent / "corrupt-snapshot.sql").read_text(),
            {
                "namespace": remote.namespace,
                "payload": canonical(as_data(corrupted)).decode(),
            },
        )

    with pytest.raises(ValueError, match="Snapshot content"):
        remote.load()
    with pytest.raises(ValueError, match="Snapshot content"):
        remote.seed(archive)
