"""
Mirror reviewed checkpoint journals in SQLite without rewriting divergent history.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from attrs import frozen

from witful.checkpoints.journal import validate
from witful.checkpoints.models import Checkpoint
from witful.exceptions import StorageError
from witful.knowledge.contracts import as_data, structure
from witful.storage import validate_endpoint

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["CheckpointStore", "SQLiteCheckpointStore", "decode", "extension", "open_store", "parameters"]
_SQL = Path(__file__).parents[1] / "sql/sqlite/checkpoints"


class CheckpointStore(Protocol):
    """
    Preserve immutable checkpoint order in a collection-specific storage partition.
    """

    def seed(self, events: Sequence[Checkpoint]) -> int:
        """
        Add a compatible history extension atomically.

        Args:
            events (Sequence[Checkpoint]): Complete validated local journal or a compatible older prefix.

        Returns:
            int: Newly inserted record count, zero for retries or older prefixes.
        """
        ...

    def load(self) -> tuple[Checkpoint, ...]:
        """
        Read and validate complete stored history.

        Returns:
            tuple[Checkpoint, ...]: Immutable records in journal order.
        """
        ...


def extension(existing: Sequence[Checkpoint], incoming: Sequence[Checkpoint]) -> Sequence[Checkpoint]:
    """
    Compare exact prefixes before accepting a transactional extension.

    Args:
        existing (Sequence[Checkpoint]): Validated database history.
        incoming (Sequence[Checkpoint]): Complete local history to seed.

    Returns:
        Sequence[Checkpoint]: New suffix; existing compatible records remain unchanged.

    Raises:
        ValueError: Histories diverge; automatic merging would lose the boundary ordering.
    """
    validate(incoming)
    shared = min(len(existing), len(incoming))

    if tuple(existing[:shared]) != tuple(incoming[:shared]):
        raise ValueError("Checkpoint histories diverge; reconcile the reviewed journal before seeding")

    return incoming[len(existing) :]


def parameters(event: Checkpoint, ordinal: int, namespace: str) -> dict[str, str | int]:
    """
    Provide bound SQL values independent of the storage dialect.

    Args:
        event (Checkpoint): Validated checkpoint.
        ordinal (int): One-based position in the history chain.
        namespace (str): Collection partition.

    Returns:
        dict[str, str | int]: Values for the separately linted insertion statement.
    """
    return {
        "namespace": namespace,
        "ordinal": ordinal,
        "id": event.id,
        "project": event.project,
        "revision": event.revision,
        "payload": json.dumps(as_data(event), sort_keys=True),
    }


def decode(rows: Sequence[tuple[object, ...]]) -> tuple[Checkpoint, ...]:
    """
    Validate stored keys, ordering, and payload content before returning history.

    Args:
        rows (Sequence[tuple[object, ...]]): Database rows ordered by ordinal.

    Returns:
        tuple[Checkpoint, ...]: Canonical checkpoint chain.

    Raises:
        ValueError: Stored metadata disagrees with its payload or the chain is corrupt.
    """
    events: list[Checkpoint] = []

    for ordinal, row in enumerate(rows, 1):
        if len(row) != 5 or row[0] != ordinal or not isinstance(row[4], str):
            raise ValueError("Invalid stored checkpoint row or order")

        event = structure(json.loads(row[4]), Checkpoint)

        if (event.id, event.project, event.revision) != row[1:4]:
            raise ValueError("Stored checkpoint metadata disagrees with its payload")

        events.append(event)

    validate(events)
    return tuple(events)


@frozen
class SQLiteCheckpointStore:
    """
    Keep a private, transactional mirror separate from disposable lesson search indexes.

    Attributes:
        path (Path): Database path under the collection's ignored runtime directory.
        namespace (str): Logical collection partition, not an authorization boundary.
    """

    path: Path
    namespace: str = "default"

    def seed(self, events: Sequence[Checkpoint]) -> int:
        """
        Insert a compatible journal suffix under a write lock.

        Args:
            events (Sequence[Checkpoint]): Complete source journal.

        Returns:
            int: Newly mirrored record count.

        Raises:
            StorageError: SQLite could not complete the transaction.
            ValueError: Existing history is corrupt or divergent.
        """
        validate(events)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.touch(mode=0o600, exist_ok=True)

        try:
            with closing(sqlite3.connect(self.path, timeout=10, isolation_level="IMMEDIATE")) as connection, connection:
                connection.executescript((_SQL / "schema.sql").read_text())
                # The driver starts an IMMEDIATE transaction before this no-op write and subsequent history read.
                connection.execute((_SQL / "lock.sql").read_text())
                rows = connection.execute((_SQL / "select.sql").read_text(), {"namespace": self.namespace}).fetchall()
                existing = decode(rows)
                added = extension(existing, events)
                connection.executemany(
                    (_SQL / "insert.sql").read_text(),
                    [parameters(event, ordinal, self.namespace) for ordinal, event in enumerate(added, len(existing) + 1)],
                )
                return len(added)
        except sqlite3.Error:
            raise StorageError("SQLite checkpoint transaction failed; inspect local database access") from None

    def load(self) -> tuple[Checkpoint, ...]:
        """
        Read a consistent stored history without creating missing tables or files.

        Returns:
            tuple[Checkpoint, ...]: Validated records, or empty when no database exists.

        Raises:
            StorageError: SQLite could not read the initialized database.
        """
        if not self.path.exists():
            return ()

        try:
            with closing(sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
                return decode(connection.execute((_SQL / "select.sql").read_text(), {"namespace": self.namespace}).fetchall())
        except sqlite3.Error:
            raise StorageError("SQLite checkpoint read failed; initialize with checkpoints sync") from None


def open_store(path: Path, endpoint: str | None, namespace: str) -> CheckpointStore:
    """
    Select an explicitly requested backend with no silent PostgreSQL fallback.

    Args:
        path (Path): SQLite database location.
        endpoint (str | None): PostgreSQL URI selected only for a sync or database read operation.
        namespace (str): Logical identity partition.

    Returns:
        CheckpointStore: Configured adapter; no connection occurs until use.
    """
    if endpoint is None:
        return SQLiteCheckpointStore(path, namespace)

    validate_endpoint(endpoint, namespace)

    try:
        from witful.checkpoints.postgres import PostgreSQLCheckpointStore
    except ImportError:
        raise StorageError("PostgreSQL checkpoints require the optional postgres dependency") from None

    return PostgreSQLCheckpointStore(endpoint, namespace)
