"""
Store checkpoint history in the existing PostgreSQL database with namespace isolation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from attrs import field, frozen

from witful.checkpoints.journal import validate
from witful.checkpoints.storage import decode, extension, parameters
from witful.storage import validate_endpoint
from witful.storage.connection import connect

if TYPE_CHECKING:
    from collections.abc import Sequence

    from witful.checkpoints.models import Checkpoint

_SQL = Path(__file__).parents[1] / "sql/postgres/checkpoints"


@frozen
class PostgreSQLCheckpointStore:
    """
    Append compatible checkpoints while keeping endpoint credentials out of representations.

    Attributes:
        database_url (str): Secret PostgreSQL URI.
        namespace (str): Logical partition within the existing application database.
    """

    database_url: str = field(repr=False)
    namespace: str = "default"

    def seed(self, events: Sequence[Checkpoint]) -> int:
        """
        Serialize initial table creation and append one compatible suffix transactionally.

        Args:
            events (Sequence[Checkpoint]): Complete validated source journal or compatible prefix.

        Returns:
            int: Number of records added; retries cannot duplicate checkpoints.
        """
        validate(events)
        validate_endpoint(self.database_url, self.namespace)

        with connect(self.database_url) as connection:
            connection.execute((_SQL.parent / "lock.sql").read_text())
            connection.execute((_SQL / "schema.sql").read_text())
            existing = decode(connection.execute((_SQL / "select.sql").read_text(), {"namespace": self.namespace}).fetchall())
            added = extension(existing, events)

            with connection.cursor() as cursor:
                cursor.executemany(
                    (_SQL / "insert.sql").read_text(),
                    [parameters(event, ordinal, self.namespace) for ordinal, event in enumerate(added, len(existing) + 1)],
                )

            return len(added)

    def load(self) -> tuple[Checkpoint, ...]:
        """
        Validate the stored hash chain independently of local source files.

        Returns:
            tuple[Checkpoint, ...]: Complete partition history in append order.
        """
        validate_endpoint(self.database_url, self.namespace)

        with connect(self.database_url) as connection:
            return decode(connection.execute((_SQL / "select.sql").read_text(), {"namespace": self.namespace}).fetchall())
