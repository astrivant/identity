"""
Seed and retrieve immutable decision archives through a transactional PostgreSQL mirror.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from sapience.knowledge.contracts import as_data, structure
from sapience.life.contracts import canonical, validate_archive
from sapience.life.models import Archive, Event, Snapshot
from sapience.storage import validate_endpoint
from sapience.storage.connection import connect

if TYPE_CHECKING:
    import psycopg

__all__ = ["PostgreSQLLifeStore"]

_SQL = Path(__file__).parents[1] / "sql/postgres/life"


@dataclass(frozen=True)
class PostgreSQLLifeStore:
    """
    Preserve journal order and reject divergent histories instead of silently combining decisions.

    Attributes:
        database_url (str): Secret URI excluded from representations.
        namespace (str): Identity partition; it is not an authorization boundary.
    """

    database_url: str = field(repr=False)
    namespace: str = "default"

    def seed(self, archive: Archive) -> int:
        """
        Atomically import a compatible journal prefix or extension without rewriting remote history.

        Args:
            archive (Archive): Fully validated events and their replay snapshots.

        Returns:
            int: Number of newly stored events; identical or older compatible prefixes add nothing.

        Raises:
            ValueError: The remote journal diverges from the supplied history.
        """
        validate_archive(archive)
        validate_endpoint(self.database_url, self.namespace)

        with connect(self.database_url) as connection:
            connection.execute((_SQL.parent / "lock.sql").read_text())
            connection.execute((_SQL / "schema.sql").read_text())
            existing = self._read(connection).events

            shared = min(len(existing), len(archive.events))

            if tuple(existing[:shared]) != archive.events[:shared]:
                raise ValueError("Remote decisions diverge; reconcile the reviewed journal before seeding")

            # Snapshot and event insertion share the transaction and lock, including concurrent first seeds.
            with connection.cursor() as cursor:
                cursor.executemany(
                    (_SQL / "insert-snapshot.sql").read_text(),
                    [
                        {"namespace": self.namespace, "id": snapshot.id, "payload": canonical(as_data(snapshot)).decode()}
                        for snapshot in archive.snapshots
                    ],
                )
                cursor.executemany(
                    (_SQL / "insert-event.sql").read_text(),
                    [
                        {
                            "namespace": self.namespace,
                            "id": event.id,
                            "ordinal": number,
                            "snapshot_id": event.snapshot_id,
                            "payload": canonical(as_data(event)).decode(),
                        }
                        for number, event in enumerate(archive.events, 1)
                        if number > len(existing)
                    ],
                )

            return max(0, len(archive.events) - len(existing))

    def load(self) -> Archive:
        """
        Read a consistent complete archive without depending on files from the original machine.

        Returns:
            Archive: Validated event history and snapshots from one database transaction.
        """
        validate_endpoint(self.database_url, self.namespace)

        with connect(self.database_url) as connection:
            # Keep the two reads consistent with the same cooperative seeders, without exposing partial batches.
            connection.execute((_SQL.parent / "lock.sql").read_text())
            return self._read(connection)

    def _read(self, connection: psycopg.Connection[tuple[object, ...]]) -> Archive:
        """
        Validate the complete remote archive under the caller's transaction and advisory lock.

        Args:
            connection (psycopg.Connection[tuple[object, ...]]): Open, bounded transaction.

        Returns:
            Archive: Validated immutable history, rejecting corrupt existing payloads before seeding.
        """
        event_rows = connection.execute((_SQL / "events.sql").read_text(), {"namespace": self.namespace}).fetchall()
        snapshot_rows = connection.execute((_SQL / "snapshots.sql").read_text(), {"namespace": self.namespace}).fetchall()
        events: list[Event] = []
        snapshots: list[Snapshot] = []

        for ordinal, row in enumerate(event_rows, 1):
            if row[0] != ordinal or not isinstance(row[2], str):
                raise ValueError("Invalid remote decision order or payload")

            event = structure(json.loads(row[2]), Event)

            if event.id != row[1]:
                raise ValueError("Remote decision key does not match its payload")

            events.append(event)

        for row in snapshot_rows:
            if not isinstance(row[1], str):
                raise ValueError("Invalid remote snapshot payload")

            snapshot = structure(json.loads(row[1]), Snapshot)

            if snapshot.id != row[0]:
                raise ValueError("Remote snapshot key does not match its payload")

            snapshots.append(snapshot)

        referenced = {event.snapshot_id for event in events}
        archive = Archive(tuple(events), tuple(snapshot for snapshot in snapshots if snapshot.id in referenced))
        validate_archive(archive)
        return archive
